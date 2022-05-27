from typing import Dict, List, Tuple

import mimesis
import mimesis.random

WeightedPool = Tuple[List[str], List[int]]


class PropertiesProvider(mimesis.BaseProvider):
    # Somewhat realistically segmented and weighted pools for random properties: device type/OS/browser
    DEVICE_TYPE_WEIGHTED_POOL: WeightedPool = (["Desktop", "Mobile", "Tablet"], [8, 1, 1])
    OS_WEIGHTED_POOLS: Dict[str, WeightedPool] = {
        "Desktop": (["Windows", "Mac OS X", "Linux", "Chrome OS"], [18, 16, 7, 1]),
        "Mobile": (["iOS", "Android"], [1, 1]),
        "Tablet": (["iOS", "Android"], [1, 1]),
    }
    BROWSER_WEIGHTED_POOLS: Dict[str, WeightedPool] = {
        "Windows": (["Chrome", "Firefox", "Opera", "Microsoft Edge", "Internet Explorer"], [12, 4, 2, 1, 1]),
        "Mac OS X": (["Chrome", "Firefox", "Opera", "Safari"], [4, 2, 1, 2]),
        "Linux": (["Chrome", "Firefox", "Opera"], [3, 3, 1]),
        "Chrome OS": (["Chrome"], [1]),
        "iOS": (["Mobile Safari", "Chrome iOS", "Firefox iOS"], [8, 1, 1]),
        "Android": (["Chrome", "Android Mobile", "Samsung Internet", "Firefox"], [5, 3, 3, 1]),
    }

    random: mimesis.random.Random

    def device_type_os_browser(self) -> Tuple[str, str, str]:
        device_type_pool, device_type_weights = self.DEVICE_TYPE_WEIGHTED_POOL
        device_type = self.random.choices(device_type_pool, device_type_weights)[0]
        os_pool, os_weights = self.OS_WEIGHTED_POOLS[device_type]
        os = self.random.choices(os_pool, os_weights)[0]
        browser_pool, browser_weights = self.BROWSER_WEIGHTED_POOLS[os]
        browser = self.random.choices(browser_pool, browser_weights)[0]
        return device_type, os, browser
