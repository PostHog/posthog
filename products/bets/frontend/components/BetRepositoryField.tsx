import { useActions, useValues } from 'kea'

import { Field, FieldDescription, FieldError, FieldLabel, Input, Skeleton } from '@posthog/quill'

import { GitHubRepositoryChips } from 'lib/integrations/GitHubRepositoryChips'

import { betFormLogic } from '../logics/betFormLogic'

export function BetRepositoryField({ id }: { id: string }): JSX.Element {
    const { repositories, repositorySource, github, githubLoading, fieldErrors } = useValues(betFormLogic({ id }))
    const { setRepositories, touch } = useActions(betFormLogic({ id }))
    const description =
        repositorySource === 'last'
            ? 'Taken from your last bet.'
            : repositorySource === 'only'
              ? 'The only repository connected to this project.'
              : repositories.length > 1
                ? 'Bets reads all of them. Pull requests go where the change belongs.'
                : 'Bets opens pull requests here when you choose an idea.'
    return (
        <Field data-invalid={!!fieldErrors.repository || undefined}>
            <FieldLabel htmlFor="bet-repository">{repositories.length > 1 ? 'Repositories' : 'Repository'}</FieldLabel>
            {githubLoading && !repositories.length ? (
                <Skeleton className="h-8 w-full" />
            ) : github?.integrationId ? (
                <div className="Bets__repositoryPicker" onBlur={() => touch('repository')}>
                    <GitHubRepositoryChips
                        integrationId={github.integrationId}
                        repositories={repositories}
                        onChange={setRepositories}
                        dataAttrPrefix="bets-form"
                    />
                </div>
            ) : (
                <Input
                    id="bet-repository"
                    value={repositories[0] ?? ''}
                    aria-invalid={!!fieldErrors.repository || undefined}
                    onChange={(event) => setRepositories(event.target.value ? [event.target.value] : [])}
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
