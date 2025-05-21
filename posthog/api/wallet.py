from rest_framework import viewsets, mixins, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from posthog.models.wallet import (
    TransactionLedger,
    Wallet,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.pagination import PageNumberPagination

class TransactionLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionLedger
        fields = [
            "id",
            "entry_type",
            "transaction_type",
            "source",
            "destination",
            "amount",
            "reference_id",
            "description",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "user_email",
        ]

class TransactionLedgerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100

class WalletViewSet(
    TeamAndOrgViewSetMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "wallet"
    permission_classes = [IsAuthenticated]
    queryset = TransactionLedger.objects.all()
    serializer_class = TransactionLedgerSerializer
    pagination_class = TransactionLedgerPagination

    def safely_get_queryset(self, queryset):
        return queryset.filter(user=self.request.user).order_by("-created_at")

    @action(detail=False, methods=["get"])
    def balance(self, request, **kwargs):
        return Response({
            "balance": Wallet.get_balance(request.user),
            "initialized": Wallet.is_initialized(request.user),
        })
    
    @action(detail=False, methods=["get"])
    def transactions(self, request, **kwargs):
        transactions = self.get_queryset()
        page = self.paginate_queryset(transactions)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(transactions, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=["post"])
    def initialize(self, request, **kwargs):
        user = request.user

        if TransactionLedger.objects.filter(user=user).exists():
            return Response({"error": "Wallet already initialized"}, status=status.HTTP_400_BAD_REQUEST)

        Wallet.initialize_wallet(user)

        return Response(
            {
                "balance": Wallet.get_balance(user),
                "initialized": True,
            }
        )