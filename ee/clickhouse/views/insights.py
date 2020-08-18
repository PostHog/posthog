from abc import ABC, abstractmethod
from typing import Any

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response


class InsightFunctions(ABC):
    @abstractmethod
    def trend(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def session(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def funnel(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def retention(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def path(self, request: Request, *args: Any, **kwargs: Any):
        pass


class ClickhouseInsights(viewsets.ViewSet, InsightFunctions):
    # TODO: add insight serializer

    def list(self, request):
        # TODO: implement get list of insights
        return Response([])

    def create(self, request):
        # TODO: implement create insights
        return Response([])

    def retrieve(self, request, pk=None):
        # TODO: implement retrieve insights by id
        return Response([])

    @action(methods=["GET"], detail=False)
    def trend(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response([])

    @action(methods=["GET"], detail=False)
    def session(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response([])

    @action(methods=["GET"], detail=False)
    def funnel(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response([])

    @action(methods=["GET"], detail=False)
    def retention(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response([])

    @action(methods=["GET"], detail=False)
    def path(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response([])
