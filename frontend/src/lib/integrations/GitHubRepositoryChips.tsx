import { IconGitRepository, IconX } from '@posthog/icons'
import { Chip, ChipClose, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { GitHubRepositoryCombobox } from './GitHubRepositoryCombobox'

export function GitHubRepositoryChips({
    integrationId,
    repositories,
    onChange,
    disabled = false,
    max = 10,
    dataAttrPrefix,
}: {
    integrationId: number
    repositories: string[]
    onChange: (repositories: string[]) => void
    disabled?: boolean
    max?: number
    dataAttrPrefix: string
}): JSX.Element {
    return (
        <div className="flex min-h-7 max-w-full flex-wrap items-center gap-2">
            {repositories.map((repository) => (
                <Chip key={repository} className="max-w-full" data-attr={`${dataAttrPrefix}-repository`}>
                    <IconGitRepository className="shrink-0 text-muted-foreground" />
                    <span className="min-w-0 truncate">{repository}</span>
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <ChipClose
                                    aria-label={`Remove ${repository}`}
                                    disabled={disabled}
                                    onClick={() => onChange(repositories.filter((item) => item !== repository))}
                                    data-attr={`${dataAttrPrefix}-remove-repository`}
                                />
                            }
                        >
                            <IconX />
                        </TooltipTrigger>
                        <TooltipContent>{`Remove ${repository}`}</TooltipContent>
                    </Tooltip>
                </Chip>
            ))}
            {repositories.length < max ? (
                <div data-attr={`${dataAttrPrefix}-add-repository`}>
                    <GitHubRepositoryCombobox
                        integrationId={integrationId}
                        value=""
                        placeholder={repositories.length ? 'Add…' : 'Add repository…'}
                        disabled={disabled}
                        onChange={(repository) => {
                            if (repository && !repositories.includes(repository)) {
                                onChange([...repositories, repository])
                            }
                        }}
                    />
                </div>
            ) : (
                <Text size="xs" variant="muted">
                    {`Up to ${max} repositories`}
                </Text>
            )}
        </div>
    )
}
