---
name: survey-sdk-audit
description: Audit PostHog survey SDK features and version requirements
---

# Surveys SDK Feature Audit Skill

Use this skill when auditing survey feature support across PostHog SDKs for `surveyVersionRequirements.ts`.

**Feature to audit:** $ARGUMENTS

## Setup Check (Run First)

Before starting, verify the SDK paths are accessible. Run `ls` on each path:

- `$POSTHOG_JS_PATH`
- `$POSTHOG_IOS_PATH`
- `$POSTHOG_ANDROID_PATH`
- `$POSTHOG_FLUTTER_PATH`

If any path is empty or doesn't exist, ask the user: "I need the path to [SDK repo] on your machine. Where is it located?"

Once you have all paths, ask the user if they'd like to save them for future sessions by adding to `.claude/settings.local.json`:

```json
{
  "env": {
    "POSTHOG_JS_PATH": "/path/to/posthog-js",
    "POSTHOG_IOS_PATH": "/path/to/posthog-ios",
    "POSTHOG_ANDROID_PATH": "/path/to/posthog-android",
    "POSTHOG_FLUTTER_PATH": "/path/to/posthog-flutter"
  },
  "permissions": {
    "allow": [
      "Read(/path/to/posthog-js/**)",
      "Read(/path/to/posthog-ios/**)",
      "Read(/path/to/posthog-android/**)",
      "Read(/path/to/posthog-flutter/**)",
      "Grep(/path/to/posthog-js/**)",
      "Grep(/path/to/posthog-ios/**)",
      "Grep(/path/to/posthog-android/**)",
      "Grep(/path/to/posthog-flutter/**)"
    ]
  }
}
```

**Note:** The `Read` and `Grep` permissions grant Claude access to these external SDK repositories without prompting each time.

## Using SDK Paths in Commands

**IMPORTANT**: Environment variables like `$POSTHOG_JS_PATH` do NOT expand reliably in Bash tool commands.

Instead of bash commands, prefer:

- **Use the Read tool** to read files (works with permissions)
- **Use the Grep tool** to search files (works with permissions)

If you must use bash, first expand the variable:

```bash
echo $POSTHOG_JS_PATH
```

Then use the echoed path directly in subsequent commands.

## Tracking Issue

All survey SDK feature parity work is tracked in:
**https://github.com/PostHog/posthog/issues/45658**

When creating new issues for missing features:

1. Create the issue in the appropriate SDK repo (see labels below)
2. Add the issue to the tracking issue's "Tracked Issues" section as a task list item:

   ```markdown
   - [ ] https://github.com/PostHog/repo/issues/123
   ```

   Note: GitHub automatically expands issue links to show titles, so no description is needed.

3. Update the relevant feature table in the tracking issue if needed

To update the tracking issue body:

**Step 1**: Fetch the current body to a temp file:

```bash
gh api repos/PostHog/posthog/issues/45658 --jq '.body' > /tmp/tracking_issue_body.md
```

**Step 2**: Use the Edit tool to modify `/tmp/tracking_issue_body.md`. This ensures the user can review the diff of your changes before proceeding.

**Step 3**: After the user has approved the edits, push the update:

```bash
gh api repos/PostHog/posthog/issues/45658 -X PATCH -f body="$(cat /tmp/tracking_issue_body.md)"
```

**Important**: Always use the Edit tool on the temp file rather than writing directly. This gives the user visibility into exactly what changes are being made to the tracking issue.

## SDK Paths and Changelogs

| SDK                  | Code Path                                | Changelog                                             |
| -------------------- | ---------------------------------------- | ----------------------------------------------------- |
| posthog-js (browser) | `$POSTHOG_JS_PATH/packages/browser`      | `$POSTHOG_JS_PATH/packages/browser/CHANGELOG.md`      |
| posthog-react-native | `$POSTHOG_JS_PATH/packages/react-native` | `$POSTHOG_JS_PATH/packages/react-native/CHANGELOG.md` |
| posthog-ios          | `$POSTHOG_IOS_PATH`                      | `$POSTHOG_IOS_PATH/CHANGELOG.md`                      |
| posthog-android      | `$POSTHOG_ANDROID_PATH`                  | `$POSTHOG_ANDROID_PATH/CHANGELOG.md`                  |
| posthog-flutter      | `$POSTHOG_FLUTTER_PATH`                  | `$POSTHOG_FLUTTER_PATH/CHANGELOG.md`                  |

## Flutter Native Dependencies

Flutter wraps native SDKs. Check dependency versions in:

- iOS: `$POSTHOG_FLUTTER_PATH/ios/posthog_flutter.podspec` (look for `s.dependency 'PostHog'`)
- Android: `$POSTHOG_FLUTTER_PATH/android/build.gradle` (look for `posthog-android` dependency)

## Audit Process

### Step 1: Understand the Feature

Look at the `check` function in `surveyVersionRequirements.ts` to understand what field/condition triggers this feature:

- `s.conditions?.deviceTypes` → search for "deviceTypes"
- `s.appearance?.fontFamily` → search for "fontFamily"
- `s.conditions?.urlMatchType` → search for "urlMatchType"

### Step 2: Search Changelogs First

```bash
# Search changelog for the feature keyword
grep -n -i "KEYWORD" /path/to/CHANGELOG.md
```

If found, read the surrounding lines to get the version number.

### Step 3: Search Code If Not in Changelog

```bash
# Find commits that added the keyword (use -S for exact string match)
cd /path/to/sdk && git log --oneline --all -S "KEYWORD" -- "*.swift" "*.kt" "*.ts" "*.tsx"

# Then find the first version tag containing that commit
git tag --contains COMMIT_HASH | sort -V | head -3
```

### Step 4: For Flutter, Find When Native Dependency Was Bumped

```bash
# Find when Flutter started requiring iOS version X.Y.Z
cd $POSTHOG_FLUTTER_PATH && git log --oneline -p -- "ios/posthog_flutter.podspec" | grep -B10 "X.Y.Z"

# Get the Flutter version for that commit
git tag --contains COMMIT_HASH | sort -V | head -1
```

### Step 5: Verify Feature Actually Works (Not Just Types)

**CRITICAL**: Having a field in a data model does NOT mean the feature is implemented. You must check the actual filtering/matching logic.

Key files to check for survey filtering logic:

- **posthog-js (browser)**: `$POSTHOG_JS_PATH/packages/browser/src/extensions/surveys/surveys-extension-utils.tsx` - utility functions like `canActivateRepeatedly`, `getSurveySeen`, `hasEvents`
- **posthog-js (browser)**: `$POSTHOG_JS_PATH/packages/browser/src/extensions/surveys.tsx` - main survey logic
- **posthog-react-native**: `$POSTHOG_JS_PATH/packages/react-native/src/surveys/getActiveMatchingSurveys.ts` - main filtering logic
- **posthog-react-native**: `$POSTHOG_JS_PATH/packages/react-native/src/surveys/surveys-utils.ts` - utility functions like `canActivateRepeatedly`, `hasEvents`
- **posthog-ios**: `$POSTHOG_IOS_PATH/PostHog/Surveys/PostHogSurveyIntegration.swift` → `getActiveMatchingSurveys()` method, `canActivateRepeatedly` computed property
- **posthog-android**: `$POSTHOG_ANDROID_PATH/posthog-android/src/main/java/com/posthog/android/surveys/PostHogSurveysIntegration.kt` → `getActiveMatchingSurveys()` method, `canActivateRepeatedly()` function

**Key utility functions to compare across SDKs:**

- `canActivateRepeatedly` - determines if a survey can be shown again after being seen
- `hasEvents` - checks if survey has event-based triggers
- `getSurveySeen` - checks if user has already seen the survey

**Example pitfall 1**: Both iOS and Android have `linkedFlagKey` in their Survey model, but neither implements `linkedFlagVariant` checking. They only call `isFeatureEnabled(key)` (boolean) instead of comparing `flags[key] === variant`.

**Example pitfall 2**: The browser `canActivateRepeatedly` checks THREE conditions: (1) event repeatedActivation, (2) `schedule === 'always'`, (3) survey in progress. Mobile SDKs may only check condition (1), missing the `schedule` check entirely.

What to look for:

- Is the field parsed from JSON into the model? (necessary but not sufficient)
- Is the field used in filtering logic like `getActiveMatchingSurveys()`?
- Does the logic match the reference implementation behavior?
- Test files don't count as implementation

## Reference Implementation

**posthog-js browser is the canonical implementation** - it has every feature and is the source of truth for how things are supposed to work.

When auditing a feature:

1. First check `$POSTHOG_JS_PATH/packages/browser/src/extensions/surveys.ts` to understand the complete, correct behavior
2. Then compare mobile SDKs against posthog-react-native (`$POSTHOG_JS_PATH/packages/react-native/src/surveys/getActiveMatchingSurveys.ts`) which is the reference for mobile-specific implementations

## Web-Only vs Cross-Platform Features

Some features only make sense on web:

- **URL targeting**: No concept of "current URL" in native apps → `issue: false` for all mobile
- **CSS selector targeting**: No DOM in native apps → `issue: false` for all mobile
- **Custom fonts via CSS**: May need native implementation or may not be applicable

## Output Format

For each feature, produce:

```typescript
{
    feature: 'Feature Name',
    sdkVersions: {
        'posthog-js': 'X.Y.Z',
        'posthog-react-native': 'X.Y.Z',  // or omit if unsupported
        'posthog-ios': 'X.Y.Z',
        'posthog-android': 'X.Y.Z',
        'posthog_flutter': 'X.Y.Z',  // add comment: first version to require native SDK >= X.Y
    },
    unsupportedSdks: [
        { sdk: 'sdk-name', issue: 'https://github.com/PostHog/repo/issues/123' },  // needs implementation
        { sdk: 'sdk-name', issue: false },  // not applicable (e.g., web-only feature)
    ],
    check: (s) => ...,
}
```

## Creating GitHub Issues

**IMPORTANT: Always search for existing issues BEFORE creating new ones.**

```bash
# Search in the SDK-specific repo
gh issue list --repo PostHog/posthog-ios --search "FEATURE_KEYWORD" --state all --limit 20
gh issue list --repo PostHog/posthog-android --search "FEATURE_KEYWORD" --state all --limit 20
gh issue list --repo PostHog/posthog-flutter --search "FEATURE_KEYWORD" --state all --limit 20

# Also search with broader terms
gh issue list --repo PostHog/posthog-ios --search "survey feature flag" --state all --limit 20
```

Always search issues in the main repo `PostHog/posthog` AND the SDK-specific repo(s) to ensure an issue does not already exist anywhere.

### Labels by Repository

| Repository              | Labels for Survey Features |
| ----------------------- | -------------------------- |
| PostHog/posthog-js      | `feature/surveys`          |
| PostHog/posthog-ios     | `Survey`, `enhancement`    |
| PostHog/posthog-android | `Survey`, `enhancement`    |
| PostHog/posthog-flutter | `Survey`, `enhancement`    |

### Issue Creation Command

```bash
# posthog-js (covers browser and react-native)
gh issue create --repo PostHog/posthog-js --label "feature/surveys" --title "..." --body "..."

# posthog-ios
gh issue create --repo PostHog/posthog-ios --label "Survey" --label "enhancement" --title "..." --body "..."

# posthog-android
gh issue create --repo PostHog/posthog-android --label "Survey" --label "enhancement" --title "..." --body "..."

# posthog-flutter
gh issue create --repo PostHog/posthog-flutter --label "Survey" --label "enhancement" --title "..." --body "..."
```

### Issue Template

```markdown
## 🚨 IMPORTANT

This issue is likely user-facing in the main PostHog app, see [`surveyVersionRequirements.ts`](https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/surveys/surveyVersionRequirements.ts). If you delete or close this issue, be sure to update the version requirements list here.

## Summary

The [SDK] SDK does not support [feature] for surveys.

## Current State

- [What exists, if anything - types, partial implementation, etc.]

## Expected Behavior

[What should happen when this feature is configured]

## Reference Implementation

See posthog-js browser: `packages/browser/src/extensions/surveys.ts`
For mobile-specific patterns, see posthog-react-native: `packages/react-native/src/surveys/getActiveMatchingSurveys.ts`

## Tracking

This is tracked in the survey SDK feature parity issue: https://github.com/PostHog/posthog/issues/45658

_This issue was generated by Claude using the `/survey-sdk-audit` skill._
```

## Completion Checklist

Before finishing the audit, verify all steps are complete:

- [ ] **Understand the feature** - Read the check function in `surveyVersionRequirements.ts`
- [ ] **Check browser SDK** - Find version in changelog (this is the reference implementation)
- [ ] **Check react-native SDK** - Find version in changelog
- [ ] **Check iOS SDK** - Verify if feature is actually implemented (not just types)
- [ ] **Check Android SDK** - Verify if feature is actually implemented (not just types)
- [ ] **Check Flutter SDK** - Check native dependency versions
- [ ] **Search for existing issues** - Before creating new ones
- [ ] **Create GitHub issues** - For any unsupported SDKs (with proper labels)
- [ ] **Update surveyVersionRequirements.ts** - Fix versions and add issue links to unsupportedSdks
- [ ] **Update tracking issue** - Add new issues to https://github.com/PostHog/posthog/issues/45658

## Common Pitfalls

1. **Don't guess versions** - always verify with changelog or git history
2. **Types ≠ Implementation** - having a field in a data class doesn't mean filtering logic exists
3. **Model field ≠ Feature support** - the field may be parsed but never used in decision-making (e.g., `linkedFlagKey` exists but `linkedFlagVariant` check is missing)
4. **Test code ≠ Production code** - functions only in test files aren't shipped
5. **Flutter inherits from native** - its "support" depends on iOS/Android SDK versions it requires
6. **Always search for existing issues first** - before creating new GitHub issues
7. **Compare utility function implementations** - functions like `canActivateRepeatedly` may have different logic across SDKs; browser is the source of truth

## Post-Audit: Skill Improvement

After completing an audit, consider whether any learnings should be added to this skill file:

1. **New pitfalls discovered** - Add to Common Pitfalls section
2. **New key files identified** - Add to the file paths in Step 5
3. **New utility functions to compare** - Add to the "Key utility functions" list
4. **Pattern changes** - If SDK implementations have changed structure, update paths

If you find improvements, propose them to the user:

```plaintext
I found some learnings during this audit that could improve the skill:
- [describe the improvement]

Would you like me to update the skill file?
```
