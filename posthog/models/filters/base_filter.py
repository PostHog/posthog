from typing import Any, Dict, Optional

from django.http import HttpRequest

from posthog.models.filters.mixins.common import BaseParamMixin


class BaseFilter(BaseParamMixin):
    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if request:
            data = {
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._data = data
