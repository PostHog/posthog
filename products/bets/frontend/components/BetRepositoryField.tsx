import { useActions, useValues } from 'kea'

import { Field, FieldDescription, FieldError, FieldLabel, Input, Skeleton } from '@posthog/quill'

import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'

import { betFormLogic } from '../logics/betFormLogic'

export function BetRepositoryField({ id }: { id: string }): JSX.Element {
    const { repository, repositorySource, github, githubLoading, fieldErrors } = useValues(betFormLogic({ id }))
    const { setRepository, touch } = useActions(betFormLogic({ id }))
    const description =
        repositorySource === 'last'
            ? 'Taken from your last bet.'
            : repositorySource === 'only'
              ? 'The only repository connected to this project.'
              : 'Bets opens pull requests here when you choose an idea.'
    return (
        <Field data-invalid={!!fieldErrors.repository || undefined}>
            <FieldLabel htmlFor="bet-repository">Repository</FieldLabel>
            {githubLoading && !repository ? (
                <Skeleton className="h-8 w-full" />
            ) : github?.integrationId ? (
                <div className="Bets__repositoryPicker [&_button]:min-h-8" onBlur={() => touch('repository')}>
                    <GitHubRepositoryCombobox
                        integrationId={github.integrationId}
                        value={repository}
                        onChange={(value) => setRepository(value ?? '')}
                        placeholder="Choose a repository"
                        fullWidth
                    />
                </div>
            ) : (
                <Input
                    id="bet-repository"
                    value={repository}
                    aria-invalid={!!fieldErrors.repository || undefined}
                    onChange={(event) => setRepository(event.target.value)}
                    onBlur={() => touch('repository')}
                    placeholder="owner/repository"
                />
            )}
            {fieldErrors.repository ? (
                <FieldError>{fieldErrors.repository}</FieldError>
            ) : (
                <FieldDescription>{description}</FieldDescription>
            )}
        </Field>
    )
}
