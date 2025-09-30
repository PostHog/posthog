from django.db import models


class DataWarehouseSavedQueryQueryType(models.TextChoices):
    """The type of query to generate"""

    REVENUE_ANALYTICS_CHARGE = ("revenue_analytics_charge", "Revenue Analytics Charge")
    REVENUE_ANALYTICS_CUSTOMER = ("revenue_analytics_customer", "Revenue Analytics Customer")
    REVENUE_ANALYTICS_PRODUCT = ("revenue_analytics_product", "Revenue Analytics Product")
    REVENUE_ANALYTICS_REVENUE_ITEM = ("revenue_analytics_revenue_item", "Revenue Analytics Revenue Item")
    REVENUE_ANALYTICS_SUBSCRIPTION = ("revenue_analytics_subscription", "Revenue Analytics Subscription")
    REVENUE_ANALYTICS_MRR = ("revenue_analytics_mrr", "Revenue Analytics MRR")
