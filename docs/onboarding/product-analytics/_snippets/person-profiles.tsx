import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

interface PersonProfilesProps {
    language?: string
    file?: string
}

export const PersonProfiles = memo(function PersonProfiles({ language = 'javascript', file }: PersonProfilesProps): JSX.Element {
    const { Markdown, CodeBlock, dedent } = useMDXComponents()

    const getCodeAndFile = () => {
        switch (language) {
            case 'python':
                return { code: '"$process_person_profile": False', file: file || 'Python' }
            case 'php':
                return { code: "'$process_person_profile' => false", file: file || 'PHP' }
            case 'elixir':
                return { code: '"$process_person_profile" => false', file: file || 'Elixir' }
            default:
                return { code: '"$process_person_profile": false', file: file || language.charAt(0).toUpperCase() + language.slice(1) }
        }
    }

    const { code, file: codeFile } = getCodeAndFile()

    return (
        <>
            <Markdown>
                By default, for backwards compatibility reasons, events are sent with [person profile
                processing](https://posthog.com/docs/data/persons) enabled. This means a person profile will be created
                for each user who triggers an event.
            </Markdown>
            <Markdown>
                If you want to disable person profile processing for certain events, send the event with the following
                property:
            </Markdown>
            <CodeBlock
                blocks={[
                    {
                        language,
                        file: codeFile,
                        code: dedent`
                            ${code}
                        `,
                    },
                ]}
            />
        </>
    )
})
