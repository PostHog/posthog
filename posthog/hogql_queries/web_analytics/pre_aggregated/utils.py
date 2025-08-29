def get_stats_table(use_v2: bool) -> str:
    return "web_pre_aggregated_stats" if use_v2 else "web_stats_combined"


def get_bounces_table(use_v2: bool) -> str:
    return "web_pre_aggregated_bounces" if use_v2 else "web_bounces_combined"
