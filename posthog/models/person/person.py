from typing import TYPE_CHECKING, Any, Optional

from django.db import connections, models, router, transaction
from django.db.models import F, Q

if TYPE_CHECKING:
    from django.db.models.query import QuerySet

from posthog.models.utils import UUIDT

from ..team import Team
from .missing_person import uuidFromDistinctId

MAX_LIMIT_DISTINCT_IDS = 2500
PERSON_ID_CUTOFF = 1000000000  # IDs < 1B in old table, >= 1B in new table

# Dual-table read preference: "old" = try old table first, "new" = try new table first
DUAL_TABLE_READ_PREFERENCE = "old"

if "persons_db_reader" in connections:
    READ_DB_FOR_PERSONS = "persons_db_reader"
elif "replica" in connections:
    READ_DB_FOR_PERSONS = "replica"
else:
    READ_DB_FOR_PERSONS = "default"


class PersonOld(models.Model):
    """Old non-partitioned person table (posthog_person)."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)
    properties_last_operation = models.JSONField(null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties = models.JSONField(default=dict)
    is_user = models.IntegerField(null=True, blank=True, db_column="is_user_id")
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "posthog_person"


class PersonNew(models.Model):
    """New hash-partitioned person table (posthog_person_new)."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)
    properties_last_operation = models.JSONField(null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties = models.JSONField(default=dict)
    is_user = models.IntegerField(null=True, blank=True, db_column="is_user_id")
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "posthog_person_new"


class DualPersonQuerySet:
    """QuerySet-like wrapper for dual-table Person queries.

    Supports method chaining and common QuerySet operations while querying
    both PersonOld and PersonNew tables.
    """

    def __init__(self, manager, q_objects=None, filters=None, excludes=None, ordering=None, db=None):
        self.manager = manager
        self.q_objects = q_objects or []  # List of Q objects for complex queries
        self.filters = filters or {}
        self.excludes = excludes or {}
        self.ordering = ordering or []
        self.db = db or "default"

    def filter(self, *args, **kwargs):
        """Chain additional filters. Supports Q objects and keyword arguments. Returns new DualPersonQuerySet."""
        new_q_objects = list(self.q_objects)
        new_q_objects.extend(args)  # Add any Q objects passed as positional args
        new_filters = {**self.filters, **kwargs}
        return DualPersonQuerySet(
            manager=self.manager,
            q_objects=new_q_objects,
            filters=new_filters,
            excludes=self.excludes,
            ordering=self.ordering,
            db=self.db,
        )

    def exclude(self, *args, **kwargs):
        """Chain exclusion filters. Supports Q objects and keyword arguments. Returns new DualPersonQuerySet."""
        new_q_objects = list(self.q_objects)
        new_q_objects.extend(args)
        new_excludes = {**self.excludes, **kwargs}
        return DualPersonQuerySet(
            manager=self.manager,
            q_objects=new_q_objects,
            filters=self.filters,
            excludes=new_excludes,
            ordering=self.ordering,
            db=self.db,
        )

    def order_by(self, *fields):
        """Add ordering. Returns new DualPersonQuerySet."""
        return DualPersonQuerySet(
            manager=self.manager,
            filters=self.filters,
            excludes=self.excludes,
            ordering=list(fields),
            db=self.db,
        )

    def count(self):
        """Execute count on both tables and return sum."""
        old_qs = PersonOld.objects.db_manager(self.db).filter(*self.q_objects, **self.filters).exclude(**self.excludes)
        new_qs = PersonNew.objects.db_manager(self.db).filter(*self.q_objects, **self.filters).exclude(**self.excludes)

        if self.ordering:
            old_qs = old_qs.order_by(*self.ordering)
            new_qs = new_qs.order_by(*self.ordering)

        return old_qs.count() + new_qs.count()

    def values_list(self, *fields, flat=False):
        """Execute on both tables and return merged list of values."""
        old_qs = PersonOld.objects.db_manager(self.db).filter(*self.q_objects, **self.filters).exclude(**self.excludes)
        new_qs = PersonNew.objects.db_manager(self.db).filter(*self.q_objects, **self.filters).exclude(**self.excludes)

        if self.ordering:
            old_qs = old_qs.order_by(*self.ordering)
            new_qs = new_qs.order_by(*self.ordering)

        old_values = list(old_qs.values_list(*fields, flat=flat))
        new_values = list(new_qs.values_list(*fields, flat=flat))

        return old_values + new_values

    def _execute(self):
        """Execute query on both tables and return merged Person instances."""
        old_qs = PersonOld.objects.db_manager(self.db).filter(*self.q_objects, **self.filters).exclude(**self.excludes)
        new_qs = PersonNew.objects.db_manager(self.db).filter(*self.q_objects, **self.filters).exclude(**self.excludes)

        if self.ordering:
            old_qs = old_qs.order_by(*self.ordering)
            new_qs = new_qs.order_by(*self.ordering)

        # Convert model instances to Person class for FK compatibility
        old_results = list(old_qs)
        new_results = list(new_qs)

        for result in old_results + new_results:
            result.__class__ = Person

        return old_results + new_results

    def __getitem__(self, key):
        """Support slicing: queryset[start:end]"""
        results = self._execute()
        return results[key]

    def __iter__(self):
        """Support iteration: for person in queryset"""
        return iter(self._execute())

    def __len__(self):
        """Support len(queryset)"""
        return self.count()


class DualPersonManager(models.Manager):
    """Manager that reads from both person tables during migration.

    Provides dual-table read support by:
    - get(): Tries preferred table first (configurable), falls back to other
    - filter(): Returns UNION of both tables (QuerySet, but limited operations)
    - Helper methods for explicit routing (get_by_id, get_by_uuid)
    """

    def _union_both_tables(self, method: str, *args, **kwargs) -> list:
        """Helper to query both tables and union results.

        Args:
            method: Method name to call ('filter' or 'exclude')
            *args, **kwargs: Arguments to pass to the method

        Returns:
            List of Person instances from both tables
        """
        old_qs = getattr(PersonOld.objects, method)(*args, **kwargs)
        new_qs = getattr(PersonNew.objects, method)(*args, **kwargs)
        union_qs = old_qs.union(new_qs)

        # Cast instances to Person type
        results = []
        for instance in union_qs:
            instance.__class__ = Person
            results.append(instance)
        return results

    def get(self, *args, **kwargs):
        """Get person from either table, trying preferred table first.

        Supports special cases:
        - pk=X where X >= 1B: MUST be in new table (can route directly)
        - pk=X where X < 1B: Could be in either, check preferred first
        - Other kwargs: try preferred table first, fallback to other
        """
        # If pk >= cutoff, we KNOW it's in new table
        if "pk" in kwargs and kwargs["pk"] >= PERSON_ID_CUTOFF:
            person = PersonNew.objects.get(*args, **kwargs)
            person.__class__ = Person
            return person

        # Otherwise try preferred table first
        first_model = PersonOld if DUAL_TABLE_READ_PREFERENCE == "old" else PersonNew
        second_model = PersonNew if DUAL_TABLE_READ_PREFERENCE == "old" else PersonOld

        try:
            person = first_model.objects.get(*args, **kwargs)
            person.__class__ = Person
            return person
        except first_model.DoesNotExist:
            try:
                person = second_model.objects.get(*args, **kwargs)
                person.__class__ = Person
                return person
            except second_model.DoesNotExist:
                raise Person.DoesNotExist()

    def filter(self, *args, **kwargs):
        """Filter across both tables, returning DualPersonQuerySet.

        Returns a QuerySet-like object that supports chaining (.filter(), .exclude(), .order_by())
        and terminal operations (.count(), .values_list(), slicing, iteration).
        """
        return DualPersonQuerySet(manager=self, filters=kwargs, db=self._db)

    def create(self, *args: Any, **kwargs: Any):
        """Handle person creation with distinct_ids support.

        During migration: creates go to old table by default.
        TODO: After migration, route new IDs to new table based on sequence.
        """
        with transaction.atomic(using=self.db):
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person._add_distinct_ids(distinct_ids)
            return person

    def get_by_id(self, person_id: int, team_id: Optional[int] = None):
        """Get person by ID, routing based on ID cutoff.

        IDs >= cutoff MUST be in new table.
        IDs < cutoff could be in either, check preferred first.
        """
        if person_id >= PERSON_ID_CUTOFF:
            # MUST be in new table
            query = PersonNew.objects.filter(id=person_id)
            if team_id is not None:
                query = query.filter(team_id=team_id)
            result = query.first()
        else:
            # Could be in either, try preferred first
            first_model = PersonOld if DUAL_TABLE_READ_PREFERENCE == "old" else PersonNew
            second_model = PersonNew if DUAL_TABLE_READ_PREFERENCE == "old" else PersonOld

            query = first_model.objects.filter(id=person_id)
            if team_id is not None:
                query = query.filter(team_id=team_id)
            result = query.first()

            if not result:
                query = second_model.objects.filter(id=person_id)
                if team_id is not None:
                    query = query.filter(team_id=team_id)
                result = query.first()

        # Convert to Person instance for compatibility with FK relations
        if result:
            result.__class__ = Person
        return result

    def filter_by_id_queryset(self, person_id: int, team_id: int, db: Optional[str] = None) -> "QuerySet":
        """Get QuerySet for person by ID, routing to correct table.

        Returns a real QuerySet (not a list) that supports .annotate(), .select_related(), etc.
        Used when code needs QuerySet operations after filtering by person_id.

        Args:
            person_id: The person ID to filter by
            team_id: Team ID to filter by
            db: Optional database alias (e.g., READ_ONLY_DATABASE_FOR_PERSONS)

        Returns:
            QuerySet from PersonOld or PersonNew that can be chained with other operations
        """
        db = db or "default"

        # Route to correct table based on ID cutoff
        if person_id >= PERSON_ID_CUTOFF:
            # Must be in new table
            return PersonNew.objects.db_manager(db).filter(team_id=team_id, id=person_id)
        else:
            # Could be in either table, try old first
            qs = PersonOld.objects.db_manager(db).filter(team_id=team_id, id=person_id)
            # If not found in old table, check new table
            if not qs.exists():
                return PersonNew.objects.db_manager(db).filter(team_id=team_id, id=person_id)
            return qs

    def exclude(self, *args, **kwargs):
        """Exclude across both tables, returning DualPersonQuerySet.

        Returns a QuerySet-like object that supports chaining and terminal operations.
        """
        return DualPersonQuerySet(manager=self, excludes=kwargs, db=self._db)

    def filter_by_cohort(self, cohort_id: int):
        """Get persons in a cohort, dual-table aware.

        Replaces pattern: Person.objects.filter(cohort__id=cohort_id)
        which uses reverse FK lookup that doesn't work with dual tables.

        Args:
            cohort_id: The cohort ID to filter by

        Returns:
            DualPersonQuerySet that supports .count(), .filter(), etc.
        """
        from posthog.models.cohort import CohortPeople

        person_ids = CohortPeople.objects.filter(cohort_id=cohort_id).values_list("person_id", flat=True)
        return self.filter(id__in=person_ids)

    def exclude_cohort(self, cohort_id: int):
        """Exclude persons in a cohort, dual-table aware.

        Replaces pattern: Person.objects.exclude(cohort__id=cohort_id)
        which uses reverse FK lookup that doesn't work with dual tables.

        Args:
            cohort_id: The cohort ID to exclude

        Returns:
            DualPersonQuerySet that supports .count(), .filter(), etc.
        """
        from posthog.models.cohort import CohortPeople

        person_ids = CohortPeople.objects.filter(cohort_id=cohort_id).values_list("person_id", flat=True)
        return self.exclude(id__in=person_ids)

    def get_by_uuid(self, team_id: int, uuid: str):
        """Get person by UUID, trying new table first then falling back to old."""
        person = PersonNew.objects.filter(team_id=team_id, uuid=uuid).first()
        if not person:
            person = PersonOld.objects.filter(team_id=team_id, uuid=uuid).first()
        # Convert to Person instance for compatibility with FK relations
        if person:
            person.__class__ = Person
        return person

    def get_by_distinct_id(self, team_id: int, distinct_id: str):
        """Get person by distinct_id, dual-table aware.

        Replaces pattern: Person.objects.get(persondistinctid__distinct_id=...)
        which uses reverse FK lookup that doesn't work with dual tables.

        Args:
            team_id: Team ID to filter by
            distinct_id: The distinct_id to look up

        Returns:
            Person instance if found, None if not found

        Raises:
            Person.DoesNotExist: If no person found for this distinct_id
        """
        from posthog.models.person import PersonDistinctId

        pdi = PersonDistinctId.objects.filter(team_id=team_id, distinct_id=distinct_id).first()
        if not pdi:
            raise Person.DoesNotExist(f"No Person found with distinct_id={distinct_id}")

        # Use get_by_id which handles dual-table routing
        return self.get_by_id(pdi.person_id, team_id=team_id)

    def get_uuids_by_person_ids(self, team_id: int, person_ids: "QuerySet", db: Optional[str] = None) -> list[str]:
        """Get UUIDs for a list of person IDs, dual-table aware.

        Args:
            team_id: Team ID to filter by
            person_ids: QuerySet of person IDs to look up
            db: Optional database alias (e.g., READ_ONLY_DATABASE_FOR_PERSONS)

        Returns:
            List of UUID strings
        """
        db = db or "default"

        # Convert QuerySet to list to query both tables
        person_ids_list = list(person_ids)
        if not person_ids_list:
            return []

        # Query both tables and combine results
        old_uuids = list(
            PersonOld.objects.db_manager(db)
            .filter(team_id=team_id, id__in=person_ids_list)
            .values_list("uuid", flat=True)
        )

        new_uuids = list(
            PersonNew.objects.db_manager(db)
            .filter(team_id=team_id, id__in=person_ids_list)
            .values_list("uuid", flat=True)
        )

        # Return combined unique UUIDs
        return [str(uuid) for uuid in set(old_uuids + new_uuids)]

    def filter_by_distinct_ids(self, team_id: int, distinct_ids: list[str], db: Optional[str] = None) -> list["Person"]:
        """Get persons by distinct IDs, dual-table aware with prefetch.

        Queries both posthog_person (old) and posthog_person_new tables, combining results.
        Results have distinct_ids_cache prefetched for efficient distinct_ids access.

        Replaces: get_persons_by_distinct_ids() util function

        Args:
            team_id: Team ID to filter by
            distinct_ids: List of distinct_ids to look up
            db: Optional database alias (e.g., READ_ONLY_DATABASE_FOR_PERSONS)

        Returns:
            List of Person instances with distinct_ids_cache prefetched
        """
        from posthog.models.person import PersonDistinctId

        db = db or READ_DB_FOR_PERSONS

        # Step 1: Get person_ids from PersonDistinctId
        person_ids = list(
            PersonDistinctId.objects.db_manager(db)
            .filter(team_id=team_id, distinct_id__in=distinct_ids)
            .values_list("person_id", flat=True)
            .distinct()
        )

        if not person_ids:
            return []

        # Step 2: Query both tables
        old_persons = list(PersonOld.objects.db_manager(db).filter(id__in=person_ids, team_id=team_id))
        new_persons = list(PersonNew.objects.db_manager(db).filter(id__in=person_ids, team_id=team_id))

        # Step 3: Manually prefetch PersonDistinctId for all persons
        all_person_ids = [p.id for p in old_persons] + [p.id for p in new_persons]
        if all_person_ids:
            distinct_id_objects = list(
                PersonDistinctId.objects.db_manager(db).filter(person_id__in=all_person_ids, team_id=team_id)
            )

            # Group by person_id
            person_to_distinct_ids: dict[int, list] = {}
            for did in distinct_id_objects:
                person_to_distinct_ids.setdefault(did.person_id, []).append(did)

            # Attach to persons as distinct_ids_cache
            for person in old_persons + new_persons:
                person.distinct_ids_cache = person_to_distinct_ids.get(person.id, [])

        # Step 4: Cast to Person type and return
        results = []
        for person in old_persons:
            person.__class__ = Person
            results.append(person)
        for person in new_persons:
            person.__class__ = Person
            results.append(person)

        return results

    def filter_by_uuids(
        self,
        team_id: int,
        uuids: list[str],
        distinct_id_limit: int = 1000,
        order_by: Optional[list[str]] = None,
        only_fields: Optional[list[str]] = None,
        db: Optional[str] = None,
    ) -> list["Person"]:
        """Get persons by UUIDs, dual-table aware with prefetch/ordering/field limiting.

        Queries both posthog_person (old) and posthog_person_new tables, combining results.
        Manually implements prefetching, ordering, and field limiting.

        Replaces: get_persons_by_uuids() util function

        Args:
            team_id: Team ID to filter by
            uuids: List of person UUIDs to fetch
            distinct_id_limit: Max PersonDistinctId objects to fetch per person
            order_by: List of fields to order by (e.g., ["-created_at", "uuid"])
            only_fields: List of fields to load (defers all others)
            db: Optional database alias (e.g., READ_ONLY_DATABASE_FOR_PERSONS)

        Returns:
            List of Person instances with distinct_ids_cache prefetched
        """
        from posthog.models.person import PersonDistinctId

        db = db or READ_DB_FOR_PERSONS

        if not uuids:
            return []

        # Query both tables
        old_qs = PersonOld.objects.db_manager(db).filter(uuid__in=uuids, team_id=team_id)
        new_qs = PersonNew.objects.db_manager(db).filter(uuid__in=uuids, team_id=team_id)

        # Apply field limiting if requested
        if only_fields:
            old_qs = old_qs.only(*only_fields)
            new_qs = new_qs.only(*only_fields)

        # Fetch results
        old_persons = list(old_qs)
        new_persons = list(new_qs)

        # Manually prefetch PersonDistinctId for all persons
        all_person_ids = [p.id for p in old_persons] + [p.id for p in new_persons]
        if all_person_ids:
            # Fetch PersonDistinctId objects with limit per person
            distinct_id_objects = list(
                PersonDistinctId.objects.db_manager(db).filter(person_id__in=all_person_ids, team_id=team_id)[
                    : distinct_id_limit * len(all_person_ids)
                ]
            )

            # Group by person_id and apply limit
            person_to_distinct_ids: dict[int, list] = {}
            for did in distinct_id_objects:
                if did.person_id not in person_to_distinct_ids:
                    person_to_distinct_ids[did.person_id] = []
                if len(person_to_distinct_ids[did.person_id]) < distinct_id_limit:
                    person_to_distinct_ids[did.person_id].append(did)

            # Attach to persons as distinct_ids_cache
            for person in old_persons + new_persons:
                person.distinct_ids_cache = person_to_distinct_ids.get(person.id, [])

        # Cast to Person type
        results = []
        for person in old_persons:
            person.__class__ = Person
            results.append(person)
        for person in new_persons:
            person.__class__ = Person
            results.append(person)

        # Apply ordering if requested
        if order_by:
            for field in reversed(order_by):
                reverse = field.startswith("-")
                field_name = field.lstrip("-")
                results.sort(key=lambda x: getattr(x, field_name, None) or "", reverse=reverse)

        return results


class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic(using=self.db):
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person._add_distinct_ids(distinct_ids)
            return person


class Person(models.Model):
    id = models.BigAutoField(primary_key=True)
    _distinct_ids: Optional[list[str]]

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation = models.JSONField(null=True, blank=True)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties = models.JSONField(default=dict)
    is_user = models.IntegerField(null=True, blank=True, db_column="is_user_id")
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)

    # current version of the person, used to sync with ClickHouse and collapse rows correctly
    version = models.BigIntegerField(null=True, blank=True)

    # Has an index on properties -> email from migration 0121, (team_id, id DESC) from migration 0164

    objects = DualPersonManager()
    legacy_objects = PersonManager()  # Keep old manager for backward compatibility

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        db_table = "posthog_person"  # Default table, DualPersonManager routes reads based on ID

    @property
    def distinct_ids(self) -> list[str]:
        if hasattr(self, "distinct_ids_cache"):
            return [id.distinct_id for id in self.distinct_ids_cache]
        if hasattr(self, "_distinct_ids") and self._distinct_ids:
            return self._distinct_ids
        return [
            id[0]
            for id in PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(person=self, team_id=self.team_id)
            .order_by("id")
            .values_list("distinct_id")
        ]

    @distinct_ids.setter
    def distinct_ids(self, value: list[str]) -> None:
        """Allow setting distinct_ids for compatibility with code that assigns to it.

        NOTE: This is mainly for test compatibility. Production code should use
        add_distinct_id() or _add_distinct_ids() instead.
        """
        # Store as simple strings for _distinct_ids cache
        self._distinct_ids = value

    @property
    def email(self) -> Optional[str]:
        return self.properties.get("email")

    # :DEPRECATED: This should happen through the plugin server
    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(person=self, distinct_id=distinct_id, team_id=self.team_id)

    # :DEPRECATED: This should happen through the plugin server
    def _add_distinct_ids(self, distinct_ids: list[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    def split_person(self, main_distinct_id: Optional[str], max_splits: Optional[int] = None):
        original_person = Person.objects.get(pk=self.pk)
        distinct_ids = original_person.distinct_ids
        original_person_version = original_person.version or 0
        if not main_distinct_id:
            self.properties = {}
            self.save()
            main_distinct_id = distinct_ids[0]

        if max_splits is not None and len(distinct_ids) > max_splits:
            # Split the last N distinct_ids of the list
            distinct_ids = distinct_ids[-1 * max_splits :]

        for distinct_id in distinct_ids:
            if not distinct_id == main_distinct_id:
                db_alias = router.db_for_write(PersonDistinctId) or "default"
                with transaction.atomic(using=db_alias):
                    pdi = PersonDistinctId.objects.select_for_update().get(person=self, distinct_id=distinct_id)
                    person, _ = Person.objects.get_or_create(
                        uuid=uuidFromDistinctId(self.team_id, distinct_id),
                        team_id=self.team_id,
                        defaults={
                            # Set version higher than delete events (which use version + 100).
                            # Keep in sync with: posthog/models/person/util.py:222 (_delete_person)
                            # and plugin-server/src/utils/db/utils.ts:152 (generateKafkaPersonUpdateMessage)
                            "version": original_person_version + 101,
                        },
                    )
                    pdi.person_id = str(person.id)
                    # Set distinct_id version higher than delete events (which use pdi.version + 100).
                    # This ensures the split distinct_id overrides any deleted distinct_id.
                    pdi.version = (pdi.version or 0) + 101
                    pdi.save(update_fields=["version", "person_id"])

                from posthog.models.person.util import create_person, create_person_distinct_id

                create_person_distinct_id(
                    team_id=self.team_id,
                    distinct_id=distinct_id,
                    person_id=str(person.uuid),
                    is_deleted=False,
                    version=pdi.version,
                )
                create_person(
                    team_id=self.team_id, uuid=str(person.uuid), version=person.version, created_at=person.created_at
                )


class PersonDistinctId(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id = models.CharField(max_length=400)

    # current version of the id, used to sync with ClickHouse and collapse rows correctly for new clickhouse table
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [models.UniqueConstraint(fields=["team", "distinct_id"], name="unique distinct_id for team")]


class PersonlessDistinctId(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    distinct_id = models.CharField(max_length=400)
    is_merged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [
            models.UniqueConstraint(fields=["team", "distinct_id"], name="unique personless distinct_id for team")
        ]


class PersonOverrideMapping(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    uuid = models.UUIDField()

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [
            models.UniqueConstraint(fields=["team_id", "uuid"], name="unique_uuid"),
        ]


class PersonOverride(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    old_person_id = models.ForeignKey(
        "PersonOverrideMapping",
        db_column="old_person_id",
        related_name="person_override_old",
        on_delete=models.CASCADE,
    )
    override_person_id = models.ForeignKey(
        "PersonOverrideMapping",
        db_column="override_person_id",
        related_name="person_override_override",
        on_delete=models.CASCADE,
    )

    oldest_event = models.DateTimeField()
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [
            models.UniqueConstraint(
                fields=["team", "old_person_id"],
                name="unique override per old_person_id",
            ),
            models.CheckConstraint(
                check=~Q(old_person_id__exact=F("override_person_id")),
                name="old_person_id_different_from_override_person_id",
            ),
        ]


class PendingPersonOverride(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False


class FlatPersonOverride(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        indexes = [
            models.Index(fields=["team_id", "override_person_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "old_person_id"],
                name="flatpersonoverride_unique_old_person_by_team",
            ),
            models.CheckConstraint(
                check=~Q(old_person_id__exact=F("override_person_id")),
                name="flatpersonoverride_check_circular_reference",
            ),
        ]


def get_distinct_ids_for_subquery(person: Person | None, team: Team) -> list[str]:
    """_summary_
    Fetching distinct_ids for a person from CH is slow, so we
    fetch them from PG for certain queries. Therfore we need
    to inline the ids in a `distinct_ids IN (...)` clause.

    This can cause the query to explode for persons with many
    ids. Thus we need to limit the amount of distinct_ids we
    pass through.

    The first distinct_ids should contain the real distinct_ids
    for a person and later ones should be associated with current
    events. Therefore we union from both sides.

    Many ids are usually a sign of instrumentation issues
    on the customer side.
    """
    first_ids_limit = 100
    last_ids_limit = MAX_LIMIT_DISTINCT_IDS - first_ids_limit

    if person is not None:
        first_ids = (
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(person=person, team=team)
            .order_by("id")
            .values_list("distinct_id", flat=True)[:first_ids_limit]
        )
        last_ids = (
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(person=person, team=team)
            .order_by("-id")
            .values_list("distinct_id", flat=True)[:last_ids_limit]
        )
        distinct_ids = first_ids.union(last_ids)
    else:
        distinct_ids = []
    return list(map(str, distinct_ids))
