from enum import Enum

from products.data_warehouse.backend.types import IncrementalFieldType


class BingAdsResource(str, Enum):
    CAMPAIGNS = "campaigns"
    CAMPAIGN_PERFORMANCE_REPORT = "campaign_performance_report"
    AD_GROUP_PERFORMANCE_REPORT = "ad_group_performance_report"
    AD_PERFORMANCE_REPORT = "ad_performance_report"


REPORT_CONFIG: dict[BingAdsResource, dict] = {
    BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT: {
        "report_type": "CampaignPerformanceReportRequest",
        "column_array_type": "ArrayOfCampaignPerformanceReportColumn",
        "column_field": "CampaignPerformanceReportColumn",
        "scope_type": "AccountThroughCampaignReportScope",
        "report_name": "Campaign Performance Report",
    },
    BingAdsResource.AD_GROUP_PERFORMANCE_REPORT: {
        "report_type": "AdGroupPerformanceReportRequest",
        "column_array_type": "ArrayOfAdGroupPerformanceReportColumn",
        "column_field": "AdGroupPerformanceReportColumn",
        "scope_type": "AccountThroughAdGroupReportScope",
        "report_name": "Ad Group Performance Report",
    },
    BingAdsResource.AD_PERFORMANCE_REPORT: {
        "report_type": "AdPerformanceReportRequest",
        "column_array_type": "ArrayOfAdPerformanceReportColumn",
        "column_field": "AdPerformanceReportColumn",
        "scope_type": "AccountThroughAdGroupReportScope",
        "report_name": "Ad Performance Report",
    },
}


RESOURCE_SCHEMAS: dict[BingAdsResource, dict] = {
    BingAdsResource.CAMPAIGNS: {
        "resource_name": "campaigns",
        "primary_key": ["Id"],
        "field_names": [
            "Id",
            "Name",
            "Status",
            "BudgetType",
            "DailyBudget",
            "CampaignType",
            "TimeZone",
        ],
        "partition_keys": [],
        "partition_mode": None,
        "partition_format": None,
        "is_stats": False,
        "partition_size": 1000,
    },
    BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT: {
        "resource_name": "campaign_performance_report",
        "primary_key": ["CampaignId", "TimePeriod"],
        "field_names": [
            "TimePeriod",
            "CampaignName",
            "CampaignId",
            "Impressions",
            "Clicks",
            "Ctr",
            "AverageCpc",
            "Spend",
            "Conversions",
            "Revenue",
        ],
        "partition_keys": ["TimePeriod"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "is_stats": True,
        "partition_size": 1,
        "filter_field_names": [("TimePeriod", IncrementalFieldType.Date)],
    },
    BingAdsResource.AD_GROUP_PERFORMANCE_REPORT: {
        "resource_name": "ad_group_performance_report",
        "primary_key": ["AdGroupId", "TimePeriod"],
        "field_names": [
            "TimePeriod",
            "AccountName",
            "CampaignName",
            "CampaignId",
            "AdGroupName",
            "AdGroupId",
            "Impressions",
            "Clicks",
            "Ctr",
            "AverageCpc",
            "Spend",
            "Conversions",
            "Revenue",
        ],
        "partition_keys": ["TimePeriod"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "is_stats": True,
        "partition_size": 1,
        "filter_field_names": [("TimePeriod", IncrementalFieldType.Date)],
    },
    BingAdsResource.AD_PERFORMANCE_REPORT: {
        "resource_name": "ad_performance_report",
        "primary_key": ["AdId", "TimePeriod"],
        "field_names": [
            "TimePeriod",
            "AccountName",
            "CampaignName",
            "CampaignId",
            "AdGroupName",
            "AdGroupId",
            "AdId",
            "AdTitle",
            "AdType",
            "Impressions",
            "Clicks",
            "Ctr",
            "AverageCpc",
            "Spend",
            "Conversions",
            "Revenue",
        ],
        "partition_keys": ["TimePeriod"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "is_stats": True,
        "partition_size": 1,
        "filter_field_names": [("TimePeriod", IncrementalFieldType.Date)],
    },
}
