import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const OverridePropertiesSnippet = memo(function OverridePropertiesSnippet({ language = 'javascript' }: { language?: string }): JSX.Element {
    const { CodeBlock, dedent, Markdown } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            posthog.setPersonPropertiesForFlags({'property1': 'value', property2: 'value2'})
        `,
        'node.js': dedent`
            await client.getFeatureFlag(
                'flag-key',
                'distinct_id_of_the_user',
                {
                    personProperties: {
                        'property_name': 'value'
                    },
                    groups: {
                        "your_group_type": "your_group_id",
                        "another_group_type": "your_group_id",
                    },
                    groupProperties: {
                        'your_group_type': {
                            'group_property_name': 'value'
                        },
                        'another_group_type': {
                            'group_property_name': 'value'
                        },
                    },
                }
            )
        `,
        python: dedent`
            posthog.get_feature_flag(
                'flag-key',
                'distinct_id_of_the_user',
                person_properties={'property_name': 'value'},
                groups={
                    'your_group_type': 'your_group_id',
                    'another_group_type': 'your_group_id'},
                group_properties={
                    'your_group_type': {'group_property_name': 'value'},
                    'another_group_type': {'group_property_name': 'value'}
                },
            )
        `,
        php: dedent`
            PostHog::getFeatureFlag(
                'flag-key',
                'distinct_id_of_the_user',
                [
                    'your_group_type' => 'your_group_id',
                    'another_group_type' => 'your_group_id'
                ], // groups
                ['property_name' => 'value'], // person properties
                [
                    'your_group_type' => ['group_property_name' => 'value'],
                    'another_group_type' => ['group_property_name' => 'value']
                ], // group properties
                false, // onlyEvaluateLocally, Optional. Defaults to false.
                true // sendFeatureFlagEvents
            )
        `,
        ruby: dedent`
            posthog.get_feature_flag(
                'flag-key',
                'distinct_id_of_the_user',
                person_properties: {
                    'property_name': 'value'
                },
                groups: {
                    'your_group_type': 'your_group_id',
                    'another_group_type': 'your_group_id',
                },
                group_properties: {
                    'your_group_type': {
                        'group_property_name': 'value'
                    },
                    'another_group_type': {
                        'group_property_name': 'value'
                    },
                },
            )
        `,
        go: dedent`
            enabledVariant, err := client.GetFeatureFlag(
                FeatureFlagPayload{
                    Key:        "flag-key",
                    DistinctId: "distinct_id_of_the_user",
                    Groups: posthog.NewGroups().
                        Set("your_group_type", "your_group_id").
                        Set("another_group_type", "your_group_id"),
                    PersonProperties: posthog.NewProperties().
                        Set("property_name", "value"),
                    GroupProperties: map[string]map[string]interface{}{
                        "your_group_type": {
                            "group_property_name": "value",
                        },
                        "another_group_type": {
                            "group_property_name": "value",
                        },
                    },
                },
            )
        `,
    }

    const langMap: Record<string, string> = {
        javascript: 'javascript',
        'node.js': 'javascript',
        python: 'python',
        php: 'php',
        ruby: 'ruby',
        go: 'go',
    }

    return (
        <>
            <Markdown>
                {dedent`
                    Sometimes, you may want to evaluate feature flags using properties that haven't been ingested yet, or were set incorrectly earlier. You can provide properties to evaluate the flag with:
                `}
            </Markdown>
            <CodeBlock language={langMap[language] || 'javascript'} code={snippets[language] || snippets.javascript} />
        </>
    )
})
