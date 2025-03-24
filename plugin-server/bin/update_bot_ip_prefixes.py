import requests
import itertools


def get_prefixes_from_url(url):
    data = requests.get(url).json()
    return [
        x
        for x in itertools.chain.from_iterable(
            (prefix.get("ipv4Prefix", None), prefix.get("ipv6Prefix", None)) for prefix in data["prefixes"]
        )
        if x
    ]


def to_hog_friendly_string(ip_ranges):
    hog_friendly_string = "let known_bot_ip_prefixes := [\n"
    for index, (key, value) in enumerate(ip_ranges.items()):
        if index > 0:
            hog_friendly_string += "\n"
        hog_friendly_string += f"  // {key}\n"
        for ip in value:
            hog_friendly_string += f"  '{ip}',\n"
    hog_friendly_string += "];\n"
    return hog_friendly_string


def update_bot_ip_ranges():
    # this list is incomplete, you can help by expanding it
    ip_ranges = {
        "ahrefs": get_prefixes_from_url("https://api.ahrefs.com/v3/public/crawler-ip-ranges"),
        "bing": get_prefixes_from_url("https://www.bing.com/toolbox/bingbot.json"),
        "google": get_prefixes_from_url("https://www.gstatic.com/ipranges/goog.json"),
    }

    print(to_hog_friendly_string(ip_ranges))  # noqa: T201


if __name__ == "__main__":
    update_bot_ip_ranges()
