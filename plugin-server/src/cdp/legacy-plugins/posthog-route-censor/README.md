# Posthog Route Censor Plugin 🚓

This plugin allows you to censor variables from URLs that are passed to PostHog. This is useful because PostHog tracks certain URLs automatically, so if your app contains sensitive data within the URLs (such as sensitive IDs, addresses, etc.), then this offers away to censor that data before it is stored in the PostHog database.

[See it on NPM here](https://www.npmjs.com/package/@avalabs/posthog-route-censor-plugin).

## Getting Started

#### Enable this Plugin for your Posthog Project

- *coming soon*

#### Locally
```sh
yarn # installs dependencies
yarn build
```

## Plugin Options

The list of properties censored by the plugin can be configured directly from the PostHog UI.

```json
    {
      "key": "routes",
      "name": "JSON list of routes following the React Router route patterns.  See package README for more details.",
      "type": "attachment",
      "hint": "See README for more details and example.",
      "required": true
    },
    {
      "key": "properties",
      "name": "List of properties to censor",
      "type": "string",
      "default": "$current_url,$referrer,$pathname,$initial_current_url,initial_pathname,initial_referrer",
      "hint": "Separate properties with commas, without using spaces, like so: `foo,bar,$baz`",
      "required": false
    },
    {
      "key": "set_properties",
      "name": "List of $set properties to censor",
      "type": "string",
      "default": "$initial_current_url,$initial_pathname,$initial_referrer",
      "hint": "Separate properties with commas, without using spaces, like so: `foo,bar,$baz`",
      "required": false
    },
    {
      "key": "set_once_properties",
      "name": "List of $set_once properties to censor",
      "type": "string",
      "default": "$initial_current_url,$initial_pathname,$initial_referrer",
      "hint": "Separate properties with commas, without using spaces, like so: `foo,bar,$baz`",
      "required": false
    }
```

### Routes

To provide routes, attach a JSON file, similar to the example at `./src/assets/exampleRoutes.json`, that matches the Routes type defined in './src/types/index.ts`.

The routes JSON includes an array of all pathnames that you would like to censor. The routes should match the pattern defined by the first parameter of the React Router V6 [matchRoutes](https://reactrouter.com/en/main/utils/match-routes) function, with an extra attribte `includes`. `includes` should contain a list of variables from the `path` pattern that you wish to censor.

#### **Example Routes JSON**

> `./src/assets/exampleRoutes.json`:

```json
[
  /**
   * This will censor the `driversLicenseId` variable from the URL.
   *
   * https://example.com/drivers-license/12345 => https://example.com/drivers-license/:driversLicenseId
   */
  {
    "path": "/drivers-license/:driversLicenseId",
    "include": ["driversLicenseId"]
  },
  /**
   * This will censor the `medicalIdNumber` variable from the URL.
   *
   * https://example.com/medical-id-number/12345 => https://example.com/medical-id-number/:medicalIdNumber
   */
  {
    "path": "/medical-id-number/:medicalIdNumber",
    "include": ["medicalIdNumber"]
  },
  /**
   * This will censor the `secretClubId` variable from the URL, but will not sensor the `categoryId` variable.
   *
   * https://example.com/secret-clubs/12345/abcde => https://example.com/secret-clubs/12345/:secretClubId
   */
  {
    "path": "/secret-clubs/:categoryId/:secretClubId",
    "include": ["secretClubId"]
  }
]
```

### Properties

> Note: you probably don't need to change this from the default values.

`properties`, `set_properties`, and `set_once_properties` are a comma separated list of properties that will be censored by this plugin. All properties in these lists should contain either a full URL (ex: "https://www.example.com/super-secret-id/1234") or a pathname (ex: "/super-secret-id/1234"). The default values should already include all properties with URLs that PostHog tracks by default, but more can be added to this list when configuring your plugin if needed.

### Caveats:

- Any properties previously defined for a user by `$set_once` cannot be overwritten by this plugin. It can only overwrite `$set_once` properties when they are initially set.
- The routes JSON must be updated whenever a new route is added to your app.
