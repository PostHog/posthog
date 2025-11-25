import re
import json
import uuid
import string
import secrets
import datetime
from collections import defaultdict, namedtuple
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from time import time, time_ns
from typing import TYPE_CHECKING, Any, Optional, TypeVar, Union
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, models, transaction
from django.db.backends.ddl_references import Statement
from django.db.backends.utils import CursorWrapper
from django.db.models import Q, UniqueConstraint
from django.db.models.constraints import BaseConstraint
from django.utils.text import slugify

from posthog.hogql import ast

from posthog.constants import MAX_SLUG_LENGTH
from posthog.person_db_router import PERSONS_DB_MODELS

if TYPE_CHECKING:
    from random import Random

T = TypeVar("T")

BASE62 = string.digits + string.ascii_letters  # All lowercase ASCII letters + all uppercase ASCII letters + digits


class UUIDT(uuid.UUID):
    """
    Deprecated, you probably want to use UUIDv7 instead. As of May 2024 the latest RFC with the UUIv7 spec is at
    Proposed Standard (see RFC9562 https://www.rfc-editor.org/rfc/rfc9562#name-uuid-version-7). This class was written
    well before that, is still in use in PostHog, but should not be used for new columns / models / features / etc.

    UUID (mostly) sortable by generation time.

    This doesn't adhere to any official UUID version spec, but it is superior as a primary key:
    to incremented integers (as they can reveal sensitive business information about usage volumes and patterns),
    to UUID v4 (as the complete randomness of v4 makes its indexing performance suboptimal),
    and to UUID v1 (as despite being time-based it can't be used practically for sorting by generation time).

    Order can be messed up if system clock is changed or if more than 65 536 IDs are generated per millisecond
    (that's over 5 trillion events per day), but it should be largely safe to assume that these are time-sortable.

    Anatomy:
    - 6 bytes - Unix time milliseconds unsigned integer
    - 2 bytes - autoincremented series unsigned integer (per millisecond, rolls over to 0 after reaching 65 535 UUIDs in one ms)
    - 8 bytes - securely random gibberish

    Loosely based on Segment's KSUID (https://github.com/segmentio/ksuid) and on Twitter's snowflake ID
    (https://blog.twitter.com/engineering/en_us/a/2010/announcing-snowflake.html).
    """

    current_series_per_ms: dict[int, int] = defaultdict(int)

    def __init__(
        self,
        unix_time_ms: Optional[int] = None,
        uuid_str: Optional[str] = None,
        *,
        seeded_random: Optional["Random"] = None,
    ) -> None:
        if uuid_str and self.is_valid_uuid(uuid_str):
            super().__init__(uuid_str)
            return

        if unix_time_ms is None:
            unix_time_ms = int(time() * 1000)
        time_component = unix_time_ms.to_bytes(6, "big", signed=False)  # 48 bits for time, WILL FAIL in 10 895 CE
        series_component = self.get_series(unix_time_ms).to_bytes(2, "big", signed=False)  # 16 bits for series
        if seeded_random is not None:
            random_component = bytes(seeded_random.getrandbits(8) for _ in range(8))  # 64 bits for random gibberish
        else:
            random_component = secrets.token_bytes(8)  # 64 bits for random gibberish
        input_bytes = time_component + series_component + random_component
        assert len(input_bytes) == 16
        super().__init__(bytes=input_bytes)

    @classmethod
    def get_series(cls, unix_time_ms: int) -> int:
        """Get per-millisecond series integer in range [0-65536)."""
        series = cls.current_series_per_ms[unix_time_ms]
        if len(cls.current_series_per_ms) > 10_000:  # Clear class dict periodically
            cls.current_series_per_ms.clear()
            cls.current_series_per_ms[unix_time_ms] = series
        cls.current_series_per_ms[unix_time_ms] += 1
        cls.current_series_per_ms[unix_time_ms] %= 65_536
        return series

    @classmethod
    def is_valid_uuid(cls, candidate: Any) -> bool:
        if not isinstance(candidate, str):
            return False
        hex = candidate.replace("urn:", "").replace("uuid:", "")
        hex = hex.strip("{}").replace("-", "")
        if len(hex) != 32:
            return False
        return 0 <= int(hex, 16) < 1 << 128


# Delete this when we can use the version from the stdlib directly, see https://github.com/python/cpython/issues/102461
def uuid7(unix_ms_time: Optional[Union[int, str]] = None, random: Optional[Union["Random", int]] = None) -> uuid.UUID:
    # timestamp part
    unix_ms_time_int: int
    if isinstance(unix_ms_time, str):
        # parse the ISO format string, use the timestamp from that
        date = datetime.datetime.fromisoformat(unix_ms_time)
        unix_ms_time_int = int(date.timestamp() * 1000)
    elif unix_ms_time is None:
        # use the current system time
        unix_ms_time_int = time_ns() // (10**6)
    else:
        # use the provided timestamp directly
        unix_ms_time_int = unix_ms_time

    # random part
    if isinstance(random, int):
        # use the integer directly as the random component
        rand_a = random & 0x0FFF
        rand_b = random >> 12 & 0x03FFFFFFFFFFFFFFF
    elif random is not None:
        # use the provided random generator
        rand_a = random.getrandbits(12)
        rand_b = random.getrandbits(56)
    else:
        # use the system random generator
        rand_bytes = int.from_bytes(secrets.token_bytes(10), byteorder="little")
        rand_a = rand_bytes & 0x0FFF
        rand_b = (rand_bytes >> 12) & 0x03FFFFFFFFFFFFFFF

    # fixed constants
    ver = 7
    var = 0b10

    # construct the UUID int
    uuid_int = (unix_ms_time_int & 0x0FFFFFFFFFFFF) << 80
    uuid_int |= ver << 76
    uuid_int |= rand_a << 64
    uuid_int |= var << 62
    uuid_int |= rand_b
    return uuid.UUID(int=uuid_int)


class CreatedMetaFields(models.Model):
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class UpdatedMetaFields(models.Model):
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        abstract = True


class DeletedMetaFields(models.Model):
    deleted = models.BooleanField(null=True, blank=True, default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """
    Base Django Model with default autoincremented ID field replaced with UUID7.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    class Meta:
        abstract = True


class UUIDTModel(models.Model):
    """
    Deprecated, you probably want to use UUIDModel instead. As of May 2024 the latest RFC with the UUIv7 spec is at
    Proposed Standard (see RFC9562 https://www.rfc-editor.org/rfc/rfc9562#name-uuid-version-7). This class was written
    well before that, is still in use in PostHog, but should not be used for new models.

    Base Django Model with default autoincremented ID field replaced with UUIDT.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    class Meta:
        abstract = True


class UUIDTClassicModel(models.Model):
    """Base Django Model with default autoincremented ID field kept and a UUIDT field added."""

    uuid = models.UUIDField(unique=True, default=UUIDT, editable=False)

    class Meta:
        abstract = True


class BytecodeModelMixin(models.Model):
    bytecode = models.JSONField(blank=True, null=True)
    bytecode_error = models.TextField(blank=True, null=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self._refresh_bytecode()
        super().save(*args, **kwargs)

    def _refresh_bytecode(self):
        from posthog.hogql.compiler.bytecode import create_bytecode
        from posthog.hogql.errors import BaseHogQLError

        try:
            expr = self.get_expr()
            new_bytecode = create_bytecode(expr).bytecode
            if new_bytecode != self.bytecode or self.bytecode_error is None:
                self.bytecode = new_bytecode
                self.bytecode_error = None
        except BaseHogQLError as e:
            # There are several known cases when bytecode generation can fail.
            # Instead of spamming with errors, ignore those cases for now.
            if self.bytecode or self.bytecode_error != str(e):
                self.bytecode = None
                self.bytecode_error = str(e)

    def get_expr(self) -> ast.Expr:
        raise NotImplementedError()


def sane_repr(*attrs: str, include_id=True) -> Callable[[object], str]:
    if "id" not in attrs and "pk" not in attrs and include_id:
        attrs = ("id", *attrs)

    def _repr(self):
        pairs = (f"{attr}={repr(getattr(self, attr))}" for attr in attrs)
        return f"<{type(self).__name__} at {hex(id(self))}: {', '.join(pairs)}>"

    return _repr


def namedtuplefetchall(cursor):
    """Return all rows from a cursor as a namedtuple"""
    desc = cursor.description
    nt_result = namedtuple("Result", [col[0] for col in desc])  # type: ignore
    return [nt_result(*row) for row in cursor.fetchall()]


def generate_random_token(nbytes: int = 32) -> str:
    """Generate a securely random token.

    Random 32 bytes - default value here - is believed to be sufficiently secure for practically all purposes:
    https://docs.python.org/3/library/secrets.html#how-many-bytes-should-tokens-use
    """
    return int_to_base(secrets.randbits(nbytes * 8), 62)


def generate_random_token_project() -> str:
    return "phc_" + generate_random_token()  # "c" standing for "client"


def generate_random_token_personal() -> str:
    # We want 32 bytes of entropy (https://docs.python.org/3/library/secrets.html#how-many-bytes-should-tokens-use).
    # Note that we store the last 4 characters of a personal API key in plain text in the database, so that users
    # can recognize their keys in the UI. This means we need 3 bytes of extra entropy. Ultimately, we want 35 bytes.
    return "phx_" + generate_random_token(35)  # "x" standing for nothing in particular


def generate_random_token_secret() -> str:
    # Similar to personal API keys, but for retrieving feature flag definitions for local evaluation.
    return "phs_" + generate_random_token(35)  # "s" standing for "secret"


def generate_random_oauth_access_token(_request) -> str:
    return "pha_" + generate_random_token()  # "a" standing for "access"


def generate_random_oauth_refresh_token(_request) -> str:
    return "phr_" + generate_random_token()  # "r" standing for "refresh"


def mask_key_value(value: str) -> str:
    """Turn 'phx_123456abcd' into 'phx_...abcd'."""
    if len(value) < 16:
        # If the token is less than 16 characters, mask the whole token.
        # This should never happen, but want to be safe.
        return "********"
    return f"{value[:4]}...{value[-4:]}"


def int_to_base(number: int, base: int) -> str:
    if base > 62:
        raise ValueError("Cannot convert integer to base above 62")
    alphabet = BASE62[:base]
    if number < 0:
        return "-" + int_to_base(-number, base)
    value = ""
    while number != 0:
        number, index = divmod(number, len(alphabet))
        value = alphabet[index] + value
    return value or "0"


class Percentile(models.Aggregate):
    template = "percentile_disc(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"

    def __init__(self, percentile, expression, **extra):
        super().__init__(expression, percentile=percentile, **extra)


class LowercaseSlugField(models.SlugField):
    def get_prep_value(self, value: Optional[str]) -> Optional[str]:
        """Return model value formatted for use as a parameter in a query."""
        prep_value = super().get_prep_value(value)
        return prep_value.lower() if prep_value else prep_value


def generate_random_short_suffix():
    """Return a 4 letter suffix made up random ASCII letters, useful for disambiguation of duplicates."""
    return "".join(secrets.choice(string.ascii_letters) for _ in range(4))


def create_with_slug(create_func: Callable[..., T], default_slug: str = "", *args, **kwargs) -> T:
    """Run model manager create function, making sure that the model is saved with a valid autogenerated slug field."""
    slugified_name = slugify(kwargs["name"])[:MAX_SLUG_LENGTH] if "name" in kwargs else default_slug
    for retry_i in range(10):
        # This retry loop handles possible duplicates by appending `-\d` to the slug in case of an IntegrityError
        if not retry_i:
            kwargs["slug"] = slugified_name
        else:
            kwargs["slug"] = f"{slugified_name[: MAX_SLUG_LENGTH - 5]}-{generate_random_short_suffix()}"
        try:
            with transaction.atomic():
                return create_func(*args, **kwargs)
        except IntegrityError:
            continue
    raise Exception("Could not create a model instance with slug in 10 tries!")


def get_deferred_field_set_for_model(
    model: type[models.Model],
    fields_not_deferred: Optional[set[str]] = None,
    field_prefix: str = "",
) -> set[str]:
    """Return a set of field names to be deferred for a given model. Used with `.defer()` after `select_related`

    Why? `select_related` fetches the entire related objects - not allowing you to specify which fields
    you want from the related objects. Often, we only want a few fields from the related object in addition to the entire
    initial object. As a result, you can't use `.only()`. This is a helper function to make it easier to use `.defer()` in this case.
    Example of how it's used is:

    `Project.objects.select_related("team").defer(*get_deferred_field_set_for_model(Team, {"name"}, "team__"))`

    For more info, see: https://code.djangoproject.com/ticket/29072

    Parameters:
        model: the model to get deferred fields for
        fields_not_deferred: the models fields to exclude from the deferred field set
        field_prefix: a prefix to add to the field names e.g. ("team__organization__") to work in the query set
    """
    if fields_not_deferred is None:
        fields_not_deferred = set()
    return {f"{field_prefix}{x.name}" for x in model._meta.fields if x.name not in fields_not_deferred}


class UniqueConstraintByExpression(BaseConstraint):
    def __init__(self, *, name: str, expression: str, concurrently=True):
        self.name = name
        self.expression = expression
        self.concurrently = concurrently

    def constraint_sql(self, model, schema_editor):
        schema_editor.deferred_sql.append(str(self.create_sql(model, schema_editor, table_creation=True)))
        return None

    def create_sql(self, model, schema_editor, table_creation=False):
        table = model._meta.db_table
        return Statement(
            f"""
            CREATE UNIQUE INDEX {'CONCURRENTLY' if self.concurrently and not table_creation else ''} %(name)s
            ON %(table)s
            %(expression)s
            """,
            name=self.name,
            table=table,
            expression=self.expression,
        )

    def remove_sql(self, model, schema_editor):
        return Statement(
            f"""
            DROP INDEX IF EXISTS %(name)s
            """,
            name=self.name,
        )

    def deconstruct(self):
        path, args, kwargs = super().deconstruct()
        kwargs["expression"] = self.expression
        kwargs["concurrently"] = self.concurrently
        return path, args, kwargs

    def __eq__(self, other):
        if isinstance(other, UniqueConstraintByExpression):
            return self.name == other.name and self.expression == other.expression
        return super().__eq__(other)


@contextmanager
def execute_with_timeout(timeout: int, database: str = "default") -> Iterator[CursorWrapper]:
    """
    Sets a transaction local timeout for the current transaction.
    """
    with transaction.atomic(using=database):
        with connections[database].cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [timeout])
            yield cursor


def validate_rate_limit(value):
    # pattern must match throttling::SimpleRateThrottle::parse_rate
    if value is not None and value != "" and not re.match("^[0-9]+/(s|sec|m|min|h|hour|d|day)$", value):
        raise ValidationError(
            "%(value)s is not a valid rate limit format. Use formats like '5/s', '10/min', '2/hour', '1/day'.",
            params={"value": value},
        )


class RootTeamQuerySet(models.QuerySet):
    def filter(self, *args, **kwargs):
        from django.db.models import Q, Subquery

        from posthog.models.team import Team

        # TODO: Handle team as a an object as well

        if "team_id" in kwargs:
            team_id = kwargs.pop("team_id")
            parent_team_subquery = Team.objects.filter(id=team_id).values("parent_team_id")[:1]
            team_filter = Q(team_id=Subquery(parent_team_subquery)) | Q(
                team_id=team_id, team__parent_team_id__isnull=True
            )
            return super().filter(team_filter, *args, **kwargs)
        return super().filter(*args, **kwargs)


class RootTeamManager(models.Manager):
    def get_queryset(self):
        return RootTeamQuerySet(self.model, using=self._db)

    def filter(self, *args, **kwargs):
        return self.get_queryset().filter(*args, **kwargs)


class RootTeamMixin(models.Model):
    """
    This ensures that when the related team has a parent team, the model will use the parent team instead.
    This should apply to all models that should be "Project" scoped instead of "Environment" scoped.
    """

    # Set the default manager - any models that inherit from this mixin and set a custom
    # manager (e.g. `objects = CustomManager()`) will override this, so that custom manager
    # should inherit from RootTeamManager.
    objects = RootTeamManager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._meta.model_name in PERSONS_DB_MODELS:
            return self._save_in_persons_db(*args, **kwargs)

        if hasattr(self, "team") and self.team and hasattr(self.team, "parent_team") and self.team.parent_team:  # type: ignore
            self.team = self.team.parent_team  # type: ignore
        super().save(*args, **kwargs)

    def _save_in_persons_db(self, *args, **kwargs) -> None:
        """
        If the model is stored in persons db, referencing the foreign key will raise an error.
        Reference the actual table column instead and query `team` manually.
        """
        team_id: Optional[int] = getattr(self, "team_id", None)
        if team_id:
            from posthog.models import Team

            team = Team.objects.get(id=team_id)
            if hasattr(team, "parent_team") and team.parent_team:
                self.team_id = team.parent_team.id

        super().save(*args, **kwargs)


def convert_funnel_query(legacy_metric):
    # Extract and simplify series
    series = []
    for step in legacy_metric["funnels_query"]["series"]:
        step_copy = {}
        for key, value in step.items():
            if key != "name":  # Skip the name field
                step_copy[key] = value
        series.append(step_copy)

    new_metric = {"kind": "ExperimentMetric", "series": series, "metric_type": "funnel"}
    if name := legacy_metric.get("name"):
        new_metric["name"] = name

    return new_metric


def convert_trends_query(legacy_metric):
    source = legacy_metric["count_query"]["series"][0].copy()

    # Remove math_property_type if it exists
    if "math_property_type" in source:
        del source["math_property_type"]

    # Remove name if there's no math field
    if "math" not in source and "name" in source:
        del source["name"]

    new_metric = {"kind": "ExperimentMetric", "source": source, "metric_type": "mean"}

    if name := legacy_metric.get("name"):
        new_metric["name"] = name

    return new_metric


"""
Converts the old JSON structure to the new format.
Transformation rules:
1. ExperimentFunnelsQuery -> ExperimentMetric with metric_type "funnel"
    - Remove name fields from series items (except when needed)
2. ExperimentTrendsQuery -> ExperimentMetric with metric_type "mean"
    - Remove math_property_type
    - Remove name if there's no math field
"""


def convert_legacy_metric(metric):
    if metric.get("kind") == "ExperimentMetric":
        return metric  # Already new format
    if metric.get("kind") == "ExperimentFunnelsQuery":
        return convert_funnel_query(metric)
    if metric.get("kind") == "ExperimentTrendsQuery":
        return convert_trends_query(metric)
    raise ValueError(f"Unknown metric kind: {metric.get('kind')}")


def convert_legacy_metrics(metrics):
    return [convert_legacy_metric(m) for m in (metrics or [])]


def build_unique_relationship_check(related_objects: Iterable[str]):
    """Checks that exactly one object field is populated"""
    built_check_list: list[Union[Q, Q]] = []
    for field in related_objects:
        built_check_list.append(
            Q(
                *[(f"{other_field}__isnull", other_field != field) for other_field in related_objects],
                _connector="AND",
            )
        )
    return Q(*built_check_list, _connector="OR")


def build_partial_uniqueness_constraint(field: str, related_field: str, constraint_name: str):
    """
    Enforces uniqueness on {field}_{related_field}.
    All permutations of null columns must be explicit as Postgres ignores uniqueness across null columns.
    """
    return UniqueConstraint(
        fields=[field, related_field],
        name=constraint_name,
        condition=Q((f"{related_field}__isnull", False)),
    )


class ActivityDetailEncoder(json.JSONEncoder):
    def default(self, obj):
        from posthog.models.activity_logging.activity_log import ActivityContextBase, Change, Detail, Trigger

        if isinstance(obj, Detail | Change | Trigger | ActivityContextBase):
            return obj.__dict__
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, datetime.time):
            return obj.isoformat()
        if isinstance(obj, datetime.timedelta):
            return str(obj)
        if "UUIDT" in globals() and isinstance(obj, UUIDT):
            return str(obj)
        if isinstance(obj, UUID):
            return str(obj)
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "User":
            return {"first_name": obj.first_name, "email": obj.email}
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "DataWarehouseTable":
            return obj.name
        if isinstance(obj, float):
            return format(obj, ".6f").rstrip("0").rstrip(".")
        if isinstance(obj, Decimal):
            return format(obj, ".6f").rstrip("0").rstrip(".")
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "FeatureFlag":
            return {
                "id": obj.id,
                "key": obj.key,
                "name": obj.name,
                "filters": obj.filters,
                "team_id": obj.team_id,
                "deleted": obj.deleted,
                "active": obj.active,
            }
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "Insight":
            return {
                "id": obj.id,
                "short_id": obj.short_id,
            }
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "Tag":
            return {
                "id": obj.id,
                "name": obj.name,
                "team_id": obj.team_id,
            }
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "UploadedMedia":
            return {
                "id": obj.id,
                "media_location": obj.media_location,
            }
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "Role":
            return {
                "id": obj.id,
                "name": obj.name,
            }
        return json.JSONEncoder.default(self, obj)
