from posthog.constants import USER_SQL
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict


class UserSQLMixin(BaseParamMixin):
    @cached_property
    def user_sql(self) -> str:
        query = self._data.get(USER_SQL, "")
        return query

    @include_dict
    def user_sql_to_dict(self):
        return {USER_SQL: self.user_sql} if self.user_sql else {}
