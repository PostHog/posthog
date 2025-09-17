import datetime
from typing import Any, Optional

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.models import Filter
from posthog.utils import relative_date_parse


class LifecycleFilter(Filter):
    target_date: Optional[datetime.datetime] = None
    lifecycle_type: Optional[str] = None

    def __init__(
        self,
        data: Optional[dict[str, Any]] = None,
        request: Optional[Request] = None,
        **kwargs,
    ) -> None:
        super().__init__(data, request, **kwargs)

        if not data and not request:
            raise ValidationError("Must include lifecycle type and target date")

        if data:
            target_date = data.get("target_date", None)
            if target_date:
                assert self.team is not None
                self.target_date = relative_date_parse(target_date, self.team.timezone_info)
            if self.target_date is None:
                raise ValidationError("Must include specified target date")

            self.lifecycle_type = data.get("lifecycle_type", None)
            if self.lifecycle_type is None:
                raise ValidationError("Must include lifecycle type")
