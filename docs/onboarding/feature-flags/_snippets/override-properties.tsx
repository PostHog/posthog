import { memo } from 'react'

import { useMDXComponents } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

export const OverridePropertiesSnippet = memo(({ language = 'javascript' }: { language?: string }): JSX.Element => {
    const { CodeBlock, dedent, Markdown } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            posthog.setPersonPropertiesForFlags({'property1': 'value', property2: 'value2'})
        `,
        'node.js': dedent`
            const flags = await client.evaluateFlags(
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
                    flagKeys: ['flag-key'],
                }
            )
            const flagValue = flags.getFlag('flag-key')
        `,
        python: dedent`
            flags = posthog.evaluate_flags(
                'distinct_id_of_the_user',
                person_properties={'property_name': 'value'},
                groups={
                    'your_group_type': 'your_group_id',
                    'another_group_type': 'your_group_id'},
                group_properties={
                    'your_group_type': {'group_property_name': 'value'},
                    'another_group_type': {'group_property_name': 'value'}
                },
                flag_keys=['flag-key'],
            )
            flag_value = flags.get_flag('flag-key')
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
            flags, err := client.EvaluateFlags(
                posthog.EvaluateFlagsPayload{
                    DistinctId: "distinct_id_of_the_user",
                    Groups: posthog.NewGroups().
                        Set("your_group_type", "your_group_id").
                        Set("another_group_type", "your_group_id"),
                    PersonProperties: posthog.NewProperties().
                        Set("property_name", "value"),
                    GroupProperties: map[string]posthog.Properties{
                        "your_group_type": {
                            "group_property_name": "value",
                        },
                        "another_group_type": {
                            "group_property_name": "value",
                        },
                    },
                    FlagKeys: []string{"flag-key"},
                },
            )
            if err == nil && flags != nil {
                enabledVariant := flags.GetFlag("flag-key")
                _ = enabledVariant
            }
        `,
        dotnet: dedent`
            var flags = await posthog.EvaluateFlagsAsync(
                "distinct_id_of_the_user",
                options: new AllFeatureFlagsOptions
                {
                    PersonProperties = new()
                    {
                        ["property_name"] = "value",
                    },
                    Groups = new()
                    {
                        new Group("your_group_type", "your_group_id")
                        {
                            ["group_property_name"] = "value",
                        },
                        new Group("another_group_type", "your_group_id")
                        {
                            ["group_property_name"] = "value",
                        },
                    },
                }
            );
        `,
    }

    const langMap: Record<string, string> = {
        javascript: 'javascript',
        'node.js': 'javascript',
        python: 'python',
        php: 'php',
        ruby: 'ruby',
        go: 'go',
        dotnet: 'csharp',
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
