# PostHog Plugin: GeoIP

Enrich PostHog events and persons with IP location data. Simply enable this plugin - from that point on, your new events will have GeoIP data added, allowing you to locate users and run queries based on geographic data.

***Available on Cloud and self-hosted PostHog 1.24.0+***

## IP Address Detection

This plugin prefers to use event property `$ip` (which should be of type `string`), but if that is not provided,
it uses the IP address of the client that sent the event.
This way in most cases the plugin can infer the IP address without any work on your side.

## Properties

The following properties can be added to the event if its IP address can be matched to a GeoLite2 City location:

```TypeScript
$geoip_city_name?: string
$geoip_country_name?: string
$geoip_country_code?: string
$geoip_continent_name?: string
$geoip_continent_code?: string
$geoip_latitude?: number
$geoip_longitude?: number
$geoip_time_zone?: string
$geoip_subdivision_1_code?: string
$geoip_subdivision_1_name?: string
$geoip_subdivision_2_code?: string
$geoip_subdivision_2_name?: string
$geoip_subdivision_3_code?: string
$geoip_subdivision_3_name?: string
```

They are also set on the associated person same as above, plus set_once in `$initial_geoip_...` form, to record where the user was when they were first seen.


View of an example event in PostHog:

<img width="708" alt="GeoIP properties in PostHog UI" src="https://user-images.githubusercontent.com/4550621/114558202-bc076600-9c6a-11eb-9c0e-1bd3cc1f3dd7.png">

## Caveats

A case to be aware of is sending events from a server – such events, if not provided with custom property `$ip`,
will be detected as sent from the location of the data center, instead of the related user.

If you'd like this plugin to skip over an event and not add the above properties,
set property `$geoip_disable` to `true` on that event.

## Installation

1. Access PostHog's **Plugins** page from the sidebar.
1. Go to the **Advanced** tab.
1. **Fetch and install** the following URL in the **Install from GitHub, GitLab or npm** section:  
   `http://github.com/PostHog/posthog-plugin-geoip`.
1. Enable the plugin and watch your events come in with enriched data!

## Questions?

### [Join the PostHo community.](https://posthog.com/questions)
