const KNOWN_PROPERTIES: Record<string, string> = {
  $browser: "Browser",
  $browser_version: "Browser version",
  $os: "OS",
  $os_version: "OS version",
  $device_type: "Device type",
  $current_url: "URL",
  $pathname: "Path",
  $host: "Host",
  $referrer: "Referrer",
  $referring_domain: "Referring domain",
  $geoip_country_name: "Country",
  $geoip_city_name: "City",
  $screen_name: "Screen",
  $lib: "Library",
  utm_source: "UTM source",
  utm_medium: "UTM medium",
  utm_campaign: "UTM campaign",
};

export function propertyDisplayName(key: string): string {
  const known = KNOWN_PROPERTIES[key];
  if (known) return known;
  const text = key.replace(/^\$/, "").replace(/[_-]+/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
