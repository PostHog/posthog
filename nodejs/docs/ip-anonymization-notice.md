# IP Anonymization Change Notice - Action Required Within 14 Days

## IMPORTANT: You have 14 days to make changes

We're making improvements to how IP address anonymization works in PostHog. **On [DATE + 14 days], this change will take effect.** Please review the impact on your transformations below and take action if needed.

---

## 1. GeoIP (Modern Template) - `template-geoip`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'template-geoip'
  AND hf.enabled = true
  AND t.anonymize_ips = true;
```

### Impact

Your GeoIP transformation will stop enriching events with location data (city, country, latitude/longitude, etc.). Events will continue to be processed normally, but geographic properties like `$geoip_city_name`, `$geoip_country_code`, and related fields will no longer be added to your events.

### To restore GeoIP functionality

**Step 1:** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

**Step 2:** Add the "Filter Properties" transformation

1. Go to Data management -> Transformations
2. Click "New transformation"
3. Click "Create" on "Filter Properties"
4. In the "Properties to filter" field, enter `$ip`
5. Save and enable the transformation
6. **Important:** Position it AFTER your GeoIP transformation (click the priority badge to open "Reorder transformations" and drag it below GeoIP)

This ensures GeoIP can read `$ip` to add geographic properties, then Filter Properties removes `$ip` from the stored event.

**You have 14 days to make this change.**

---

## 2. Advanced GeoIP - Library-based filtering (Legacy Plugin) - `plugin-plugin-advanced-geoip`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id,
       hf.inputs->'discardLibs'->>'value' as discard_libs
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'plugin-plugin-advanced-geoip'
  AND hf.enabled = true
  AND t.anonymize_ips = true
  AND hf.inputs->'discardLibs'->>'value' IS NOT NULL
  AND hf.inputs->'discardLibs'->>'value' != ''
  AND hf.inputs->'discardLibs'->>'value' != '[]';
```

### Impact

Your Advanced GeoIP plugin is configured to **remove** GeoIP data from events coming from specific libraries (the `discardLibs` setting).

Since IP addresses will be removed before this plugin runs, the plugin will no longer be able to detect whether GeoIP processing has occurred, and its functionality will be impacted.

### To restore identical behavior

**Step 1:** Review your current configuration

1. Go to Data management -> Transformations
2. Find your "Advanced GeoIP" plugin
3. Note which libraries you're configured to filter (in the `discardLibs` setting)

**Step 2:** Create a custom transformation to remove `$ip` for specific libraries

1. Go to Data management -> Transformations
2. Click "New transformation"
3. Click "Create" on "Custom transformation"
4. Paste the following code (modify the library names to match your `discardLibs` configuration):

```hog
let lib := event.properties.$lib
let returnEvent := event

if (lib == 'posthog-ios' or lib == 'posthog-android') {
    returnEvent.properties.$ip := null
}
return returnEvent
```

5. Save and enable the transformation
6. Position it BEFORE the GeoIP transformation (click the priority badge to open "Reorder transformations" and drag it above GeoIP)

**Step 3:** Add the "GeoIP" transformation (if not already added)

1. Click "New transformation"
2. Click "Create" on "GeoIP"
3. Save and enable the transformation
4. Position it AFTER the custom transformation from Step 2 (use "Reorder transformations" to drag it into place)

**Step 4:** Add a "Filter Properties" transformation to remove `$ip` from all events

1. Click "New transformation"
2. Click "Create" on "Filter Properties"
3. In the "Properties to filter" field, enter `$ip`
4. Save and enable the transformation
5. Position it AFTER the GeoIP transformation (use "Reorder transformations" to drag it into place)

**Step 5:** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

**Step 6:** Verify the new setup is working

1. Send test events from different libraries
2. Verify GeoIP properties are NOT added for your filtered libraries (because `$ip` was removed before GeoIP ran)
3. Verify GeoIP properties ARE added for other libraries
4. Verify `$ip` is removed from all final events

**Step 7:** Disable the legacy plugin

1. Go to Data management -> Transformations
2. Find your "Advanced GeoIP" plugin
3. Disable it

**How it works:** By removing `$ip` BEFORE GeoIP runs for specific libraries, GeoIP has no IP to look up and won't add any geo properties. For other events, GeoIP runs normally, then the final Filter Properties transformation removes `$ip` from the stored event.

**You have 14 days to implement this migration.**

---

## 3. Advanced GeoIP - IP removal (Legacy Plugin) - `plugin-plugin-advanced-geoip`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id,
       hf.inputs->'discardIp'->>'value' as discard_ip
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'plugin-plugin-advanced-geoip'
  AND hf.enabled = true
  AND t.anonymize_ips = true
  AND (hf.inputs->'discardIp'->>'value' = 'true' OR hf.inputs->'discardIp'->'value' = 'true'::jsonb);
```

### Impact

Your Advanced GeoIP plugin is configured to remove IP addresses after GeoIP processing (the `discardIp` setting).

Since IP addresses will be removed before this plugin runs, this functionality is now redundant as IPs are already being removed at the ingestion level.

### Action required

**Option 1: No action needed (Recommended)**

The new system already removes IPs at the ingestion level, achieving the same result as your `discardIp` setting. You can simply disable the legacy plugin:

1. Go to Data management -> Transformations
2. Find your "Advanced GeoIP" plugin
3. Disable it

**Option 2: If you also need library-based filtering**

If your plugin also has `discardLibs` configured, follow the migration steps in Section 2 to set up custom library-based filtering.

**You have 14 days to review and disable the legacy plugin.**

---

## 4. PostHog GeoIP (Legacy Plugin) - `plugin-posthog-plugin-geoip`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'plugin-posthog-plugin-geoip'
  AND hf.enabled = true
  AND t.anonymize_ips = true;
```

### Impact

Your GeoIP transformation will stop enriching events with location data. Events will continue to be processed normally, but geographic properties will no longer be added.

### Recommended: Migrate to new GeoIP transformation

**Step 1:** Add the new "GeoIP" transformation

1. Go to Data management -> Transformations
2. Click "New transformation"
3. Click "Create" on "GeoIP" (modern template)
4. Enable the transformation

**Step 2:** Add the "Filter Properties" transformation

1. Click "New transformation"
2. Click "Create" on "Filter Properties"
3. In the "Properties to filter" field, enter `$ip`
4. Save and enable the transformation
5. **Important:** Position it AFTER your GeoIP transformation (click the priority badge to open "Reorder transformations" and drag it below GeoIP)

**Step 3:** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

**Step 4:** Verify the new setup is working

1. Send test events
2. Verify GeoIP properties are being added
3. Verify `$ip` is not present in stored events

**Step 5:** Disable the legacy plugin

1. Go to Data management -> Transformations
2. Find your legacy "PostHog GeoIP" plugin
3. Disable it

The new transformation offers better performance and is actively maintained.

**You have 14 days to complete this migration.**

---

## 5. Bot Detection - `template-bot-detection`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'template-bot-detection'
  AND hf.enabled = true
  AND t.anonymize_ips = true;
```

### Impact

Your bot detection transformation will stop filtering bot traffic based on IP addresses. Known bot IPs and custom IP ranges you configured will no longer be blocked. Events from these IPs will be processed as regular user events, potentially inflating your metrics.

**Important:** You may see an **increase in stored event volume** as bot events that were previously dropped will now be ingested and billed.

### To restore bot detection functionality

**Step 1:** Add the "Filter Properties" transformation

1. Go to Data management -> Transformations
2. Click "New transformation"
3. Click "Create" on "Filter Properties"
4. In the "Properties to filter" field, enter `$ip`
5. Position it AFTER your Bot Detection transformation (click the priority badge to open "Reorder transformations" and drag it below Bot Detection)
6. Save and enable the transformation

**Step 2:** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

### Alternative

If IP-based bot detection is not critical for your use case, consider using other bot detection methods like user agent filtering instead.

**You have 14 days to make this change before bot filtering stops working.**

---

## 6. IP Anonymization - `template-ip-anonymization`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'template-ip-anonymization'
  AND hf.enabled = true
  AND t.anonymize_ips = true;
```

### Impact

**BEHAVIOR CHANGE**: Your IP handling is changing from **anonymization** (setting last octet to 0, e.g., `192.168.1.100` -> `192.168.1.0`) to **complete removal** (IP address is deleted entirely).

The new system removes IPs at the ingestion level (before transformations run), so your IP Anonymization transformation will receive events with no `$ip` property and will effectively do nothing.

### Action required

**If you want to keep the current behavior (anonymize instead of remove):**

**Step 1:** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

**Step 2:** Verify your IP Anonymization transformation is enabled

1. Go to Data management -> Transformations
2. Find your IP Anonymization transformation
3. Verify it's enabled
4. No other changes needed - it will continue to anonymize IPs

**If you're okay with removing IPs completely instead of anonymizing:**

**Step 1:** Disable this transformation

1. Go to Data management -> Transformations
2. Find your IP Anonymization transformation
3. Disable it

**Step 2:** Verify "Discard client IP data" is enabled

1. Go to Settings -> Environment -> Product analytics
2. Verify "Discard client IP data" is ON
3. IPs will now be completely removed instead of anonymized

**You have 14 days to decide which approach you want and make the necessary changes.**

---

## 7. PII Hashing - `template-pii-hashing`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id,
       hf.inputs->'propertyKeys'->>'value' as properties_to_hash
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'template-pii-hashing'
  AND hf.enabled = true
  AND t.anonymize_ips = true
  AND hf.inputs->'propertyKeys'->>'value' LIKE '%$ip%';
```

### Impact

If your PII Hashing transformation is configured to hash `$ip` (check your transformation settings), it will no longer be able to hash IP addresses since they're removed before the transformation run. Other PII fields you're hashing (email, phone, etc.) will continue to work normally.

### To restore IP hashing functionality

**Step 1:** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

**Step 2:** Verify your PII Hashing transformation configuration

1. Go to Data management -> Transformations
2. Find your PII Hashing transformation
3. Check that `$ip` is included in the "Properties to Hash" configuration
4. If not, add it

**Step 3 (Optional):** Add "Filter Properties" transformation to remove hashed IP

1. Click "New transformation"
2. Click "Create" on "Filter Properties"
3. In the "Properties to filter" field, enter `$ip`
4. Position it AFTER your PII Hashing transformation (click the priority badge to open "Reorder transformations" and drag it below PII Hashing)
5. Save and enable the transformation

Note: Hashed IPs are already anonymized, so removing them afterward is optional.

### Alternative

If IP hashing isn't critical to your use case:

1. Go to your PII Hashing transformation settings
2. Remove `$ip` from the "Properties to Hash" configuration
3. Save changes
4. Leave "Discard client IP data" enabled

**You have 14 days to adjust your PII hashing configuration.**

---

## 8. Property Filter (Legacy Plugin) - `plugin-property-filter-plugin`

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id,
       hf.inputs as config
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.template_id = 'plugin-property-filter-plugin'
  AND hf.enabled = true
  AND t.anonymize_ips = true
  AND (
    hf.inputs::text LIKE '%$ip%'
    OR hf.inputs::text LIKE '%ip%'
  );
```

### Impact

If your Property Filter transformation is configured to filter `$ip`, it will now be a no-op since the IP is already removed. The transformation will still work for any other properties you're filtering, but the `$ip` filtering is redundant.

**Note:** If your Property Filter was configured to **drop events** based on IP address patterns (not just remove the property), those events will no longer be dropped and you may see an **increase in stored event volume**.

### If you're only filtering IP properties (not dropping events)

**No action needed** - Your Property Filter transformation will continue to work for other properties. The `$ip` filtering is now handled automatically by the "Discard client IP data" setting.

### If you're dropping events based on IP patterns

**Step 1:** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

**Step 2:** Keep your Property Filter transformation with IP rules

1. Verify it's still enabled in Data management -> Transformations
2. Verify your IP-based dropping rules are configured

**Step 3:** Add a new "Filter Properties" transformation to remove IP

1. Click "New transformation"
2. Click "Create" on "Filter Properties"
3. In the "Properties to filter" field, enter `$ip`
4. Position it AFTER your existing Property Filter (click the priority badge to open "Reorder transformations" and drag it below your existing filter)
5. Save and enable the transformation

### Recommended: Migrate to new "Filter Properties" transformation

**Step 1:** Review your current filter configuration

1. Go to Data management -> Transformations
2. Find your legacy Property Filter plugin
3. Note down all your current filter settings

**Step 2:** Add the new "Filter Properties" transformation

1. Click "New transformation"
2. Click "Create" on "Filter Properties" (modern template, ID: `template-filter-properties`)
3. Configure it with the same settings from your legacy plugin
4. Save and enable the transformation

**Step 3:** Verify the new transformation is working

1. Send test events
2. Verify filtering is working as expected

**Step 4:** Disable the legacy plugin

1. Find your legacy "Property Filter" plugin
2. Disable it

**You have 14 days to make these changes.**

---

## 9. Custom Transformations (using `$ip` in code)

### Affected teams query

```sql
SELECT t.id, t.name, t.organization_id,
       hf.name as transformation_name
FROM posthog_team t
JOIN posthog_hogfunction hf ON hf.team_id = t.id
WHERE hf.enabled = true
  AND t.anonymize_ips = true
  AND hf.template_id IS NULL
  AND (
    hf.hog LIKE '%$ip%'
    OR hf.hog LIKE '%properties.ip%'
    OR hf.hog LIKE '%properties[''ip'']%'
  );
```

### Impact

Your custom transformation references `$ip` in its code. Depending on how it's used, this could cause:

- Missing functionality if `$ip` is required for the transformation logic
- No impact if `$ip` is optional or has fallback handling
- **Potential increase in event volume** if your transformation was dropping/filtering events based on IP

**Important:** Review your transformation code to check if it drops events based on IP. If so, you may see an **increase in stored event volume and billing**.

### Action required

**Step 1:** Review your transformation code

1. Go to Data management -> Transformations
2. Find your custom transformation
3. Review how `$ip` is being used in the code
4. Determine if `$ip` is critical to functionality

**Step 2 (if `$ip` is critical):** Disable "Discard client IP data"

1. Go to Settings -> Environment -> Product analytics
2. Turn OFF "Discard client IP data"
3. Save changes

**Step 3 (if `$ip` is critical):** Add "Filter Properties" transformation

1. Click "New transformation"
2. Click "Create" on "Filter Properties"
3. In the "Properties to filter" field, enter `$ip`
4. Position it AFTER your custom transformation (click the priority badge to open "Reorder transformations" and drag it below your custom transformation)
5. Save and enable the transformation

**Step 4:** Verify everything is working

1. Send test events
2. Verify your custom transformation is working correctly
3. Verify `$ip` is not present in stored events (if using Filter Properties)

**Step 2 (if `$ip` is optional):** Verify graceful handling

1. Send test events
2. Verify your transformation handles missing `$ip` without errors
3. No further action needed if working correctly

**You have 14 days to review and update your custom transformation.**

---

## General Recommendation

**For most customers using GeoIP or Bot Detection:**

The recommended setup is:

1. Add the "Filter Properties" transformation configured to remove `$ip`
2. Turn OFF "Discard client IP data"
3. Keep your GeoIP/Bot Detection transformations enabled (or migrate to new versions)

This gives you the best of both worlds: location/bot insights WITHOUT storing raw IP addresses.

**Event Volume Impact:** If you were previously using transformations to drop events based on IP (Bot Detection, Property Filter, or custom transformations), restoring this functionality is important to avoid unexpected increases in stored events and associated costs.

**Migration from Legacy Plugins:** If you're using legacy GeoIP or Property Filter plugins, now is a great time to migrate to the modern transformation equivalents for better performance and ongoing support.

**Timeline:** This change will take effect on **[DATE + 14 days]**. Please review your settings and make any necessary changes before this date to ensure continued functionality.

**Need Help?** If you have questions or need assistance with this migration, please contact our support team at support@posthog.com or visit our documentation at [link to docs].
