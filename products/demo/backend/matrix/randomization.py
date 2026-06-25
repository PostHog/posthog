from enum import StrEnum

import mimesis.random

WeightedPool = tuple[list[str], list[int]]


class Industry(StrEnum):
    TECHNOLOGY = "technology"
    FINANCE = "finance"
    MEDIA = "media"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    ENTERTAINMENT = "entertainment"
    RETAIL = "retail"
    TRAVEL = "travel"
    FOOD = "food"
    REAL_ESTATE = "real estate"
    OTHER = "other"


class PropertiesProvider(mimesis.BaseProvider):
    # Somewhat realistically segmented and weighted pools for random properties: device type/OS/browser
    DEVICE_TYPE_WEIGHTED_POOL: WeightedPool = (
        ["Desktop", "Mobile", "Tablet", "Console", "Wearable"],
        [10, 2, 2, 1, 1],
    )
    OS_WEIGHTED_POOLS: dict[str, WeightedPool] = {
        "Desktop": (["Windows", "Mac OS X", "Linux", "Chrome OS"], [18, 16, 7, 1]),
        "Mobile": (["iOS", "Android", "Windows Mobile", "Windows Phone", "Blackberry"], [3, 3, 1, 1, 1]),
        "Tablet": (["iOS", "Android"], [1, 1]),
        "Console": (["Xbox", "Nintendo", "Playstation"], [1, 1, 1]),
        "Wearable": (["watchOS"], [1]),
    }
    BROWSER_WEIGHTED_POOLS: dict[str, WeightedPool] = {
        "Windows": (
            ["Chrome", "Firefox", "Opera", "Microsoft Edge", "Internet Explorer"],
            [12, 4, 2, 1, 1],
        ),
        "Mac OS X": (["Chrome", "Safari", "Firefox", "Opera", "Microsoft Edge"], [4, 3, 2, 1, 1]),
        "Linux": (["Chrome", "Firefox", "Opera", "Konqueror"], [3, 3, 1, 1]),
        "Chrome OS": (["Chrome"], [1]),
        "iOS": (["Mobile Safari", "Chrome iOS", "Firefox iOS", "Facebook Mobile"], [8, 1, 1, 1]),
        "Android": (
            ["Chrome", "Android Mobile", "Samsung Internet", "Firefox", "UC Browser", "Facebook Mobile"],
            [6, 4, 3, 1, 1, 1],
        ),
        "Xbox": (["Chrome"], [1]),
        "Playstation": (["Chrome"], [1]),
        "Nintendo": (["Nintendo"], [1]),
        "watchOS": (["Safari"], [1]),
        "Blackberry": (["Blackberry"], [1]),
        "Windows Phone": (["Internet Explorer Mobile", "Microsoft Edge"], [1, 1]),
        "Windows Mobile": (["Microsoft Edge"], [1]),
    }

    INDUSTRY_POOL = (
        [
            Industry.TECHNOLOGY,
            Industry.HEALTHCARE,
            Industry.FINANCE,
            Industry.EDUCATION,
            Industry.ENTERTAINMENT,
            Industry.RETAIL,
            Industry.TRAVEL,
            Industry.FOOD,
            Industry.REAL_ESTATE,
            Industry.OTHER,
        ],
        [3, 1, 1, 2, 2, 1, 2, 2, 1, 3],
    )

    random: mimesis.random.Random

    def device_type_os_browser(self) -> tuple[str, str, str]:
        device_type_pool, device_type_weights = self.DEVICE_TYPE_WEIGHTED_POOL
        device_type = self.random.choices(device_type_pool, device_type_weights)[0]
        os_pool, os_weights = self.OS_WEIGHTED_POOLS[device_type]
        os = self.random.choices(os_pool, os_weights)[0]
        browser_pool, browser_weights = self.BROWSER_WEIGHTED_POOLS[os]
        browser = self.random.choices(browser_pool, browser_weights)[0]
        return device_type, os, browser

    def industry(self) -> Industry:
        industry_pool, industry_weights = self.INDUSTRY_POOL
        return self.random.choices(industry_pool, industry_weights)[0]
