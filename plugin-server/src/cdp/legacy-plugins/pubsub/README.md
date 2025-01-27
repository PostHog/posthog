# Google Pub/Sub Plugin

Sends events to a Pub/Sub topic on ingestion.

## Installation

1. Visit 'Plugins' in PostHog
1. Find this plugin from the repository or install `https://github.com/vendasta/pubsub-plugin`
1. Configure the plugin
    1. Upload your Google Cloud key `.json` file. ([How to get the file](https://cloud.google.com/pubsub/docs/reference/libraries).)
    1. Enter your Topic ID
1. Watch events publish to Topic

## Message Format

```json
{
  "event": "$autocapture",
  "distinct_id": "U-aafca76a-45ee-491f-a801-6d6e9963c636",
  "team_id": 1,
  "ip": "111.111.111.1111",
  "site_url": "https://yoursiteurl.com",
  "timestamp": "2021-09-03T15:08:58.813971+00:00",
  "uuid": "017bac34-ae6e-0000-24f7-2ae87f5f89d9",
  "properties": {
    "$os": "Windows",
    "$browser": "Chrome",
    "$device_type": "Desktop",
    "$current_url": "",
    "$host": "",
    "$pathname": "",
    "$browser_version": 92,
    "$screen_height": 1080,
    "$screen_width": 1920,
    "$viewport_height": 975,
    "$viewport_width": 1920,
    "$lib": "web",
    "$lib_version": "1.12.3",
    "$insert_id": "mac0om92q3eoff5p",
    "$time": 1630681734.981,
    "distinct_id": "U-aafca76a-45ee-491f-a801-6d6e9963c636",
    "$device_id": "17a8c213255504-03fa008e947a61-6373264-1fa400-17a8c2132566a7",
    "$user_id": "U-aafca76a-45ee-491f-a801-6d6e9963c636",
    "$search_engine": "google",
    "$initial_referrer": "https://www.google.com/",
    "$initial_referring_domain": "www.google.com",
    "$referrer": "https://www.google.com/",
    "$referring_domain": "www.google.com",
    "$active_feature_flags": [
    ],
    "$event_type": "click",
    "$ce_version": 1,
    "token": "0GJcKFgOeBbm1q4S2TRWX8TaZif85RX5fdzVjD8AJZM",
    "$geoip_city_name": "Idukki",
    "$geoip_country_name": "India",
    "$geoip_country_code": "IN",
    "$geoip_continent_name": "Asia",
    "$geoip_continent_code": "AS",
    "$geoip_postal_code": "685501",
    "$geoip_latitude": 9.8466,
    "$geoip_longitude": 76.9689,
    "$geoip_time_zone": "Asia/Kolkata",
    "$geoip_subdivision_1_code": "KL",
    "$geoip_subdivision_1_name": "Kerala",
    "$plugins_succeeded": [
    ],
    "$plugins_failed": [
    ],
    "$plugins_deferred": [
    ]
  },
  "elements": [
  ],
  "people_set": {
    "$geoip_city_name": "Idukki",
    "$geoip_country_name": "India",
    "$geoip_country_code": "IN",
    "$geoip_continent_name": "Asia",
    "$geoip_continent_code": "AS",
    "$geoip_postal_code": "685501",
    "$geoip_latitude": 9.8466,
    "$geoip_longitude": 76.9689,
    "$geoip_time_zone": "Asia/Kolkata",
    "$geoip_subdivision_1_code": "KL",
    "$geoip_subdivision_1_name": "Kerala"
  },
  "people_set_once": {
    "$initial_geoip_city_name": "Idukki",
    "$initial_geoip_country_name": "India",
    "$initial_geoip_country_code": "IN",
    "$initial_geoip_continent_name": "Asia",
    "$initial_geoip_continent_code": "AS",
    "$initial_geoip_postal_code": "685501",
    "$initial_geoip_latitude": 9.8466,
    "$initial_geoip_longitude": 76.9689,
    "$initial_geoip_time_zone": "Asia/Kolkata",
    "$initial_geoip_subdivision_1_code": "KL",
    "$initial_geoip_subdivision_1_name": "Kerala"
  }
}
```
