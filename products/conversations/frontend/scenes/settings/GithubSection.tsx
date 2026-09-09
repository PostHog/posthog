import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Badge,
    Button,
    Card,
    CardContent,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    useComboboxAnchor,
} from 'lib/ui/quill'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function GithubSection(): JSX.Element {
    return (
        <SceneSection
            title="GitHub Issues"
            description={
                <>
                    Connect a GitHub App installation to sync issues as support tickets. Comments sync bidirectionally —
                    replies from PostHog appear on the GitHub issue.
                </>
            }
        >
            <Card size="sm" className="max-w-[800px]">
                <CardContent>
                    <GithubConnectionSection />
                </CardContent>
            </Card>
        </SceneSection>
    )
}

function GithubConnectionSection(): JSX.Element {
    const { githubConnected, githubRepos, githubReposLoading, githubSelectedRepos, githubIntegrations } =
        useValues(supportSettingsLogic)
    const { connectGithub, disconnectGithub, setGithubRepos, loadGithubRepos } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    if (!githubConnected) {
        if (githubIntegrations.length === 0) {
            return (
                <div className="flex flex-col gap-y-2">
                    <label className="font-medium">Connection</label>
                    <p className="text-xs text-muted-alt">
                        First, install the PostHog GitHub App from the integrations page, then come back here to select
                        which repositories to monitor.
                    </p>
                    <Button
                        variant="primary"
                        size="sm"
                        className="mt-1 self-start"
                        disabled={!!adminRestrictionReason}
                        title={adminRestrictionReason ?? undefined}
                        render={<LinkPrimitive to="/integrations/github" />}
                    >
                        Go to GitHub integration
                    </Button>
                </div>
            )
        }

        return (
            <div className="flex flex-col gap-y-2">
                <label className="font-medium">Connection</label>
                <p className="text-xs text-muted-alt">
                    Select a GitHub App installation to connect. Issues from selected repositories will become support
                    tickets.
                </p>
                <div className="flex flex-wrap gap-2 mt-1">
                    {githubIntegrations.map((integration) => (
                        <Button
                            key={integration.id}
                            variant="primary"
                            size="sm"
                            disabled={!!adminRestrictionReason}
                            title={adminRestrictionReason ?? undefined}
                            onClick={() => connectGithub(integration.id)}
                        >
                            Connect {integration.name || `Installation #${integration.id}`}
                        </Button>
                    ))}
                </div>
            </div>
        )
    }

    const repoOptions = githubRepos.map((r) => ({ id: r.full_name, label: r.full_name }))

    return (
        <div className="flex flex-col gap-y-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <label className="font-medium mb-0">GitHub Issues</label>
                    <Badge variant="success">Connected</Badge>
                </div>
                <AlertDialog>
                    <AlertDialogTrigger
                        render={
                            <Button
                                variant="outline"
                                size="xs"
                                disabled={!!adminRestrictionReason}
                                title={adminRestrictionReason ?? undefined}
                            />
                        }
                    >
                        Disconnect
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Disconnect GitHub?</AlertDialogTitle>
                            <AlertDialogDescription>
                                New issues will no longer create tickets. Existing tickets will remain but replies will
                                not sync.
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                            <AlertDialogClose render={<Button variant="destructive" onClick={disconnectGithub} />}>
                                Disconnect
                            </AlertDialogClose>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            </div>

            <div>
                <label className="font-medium">Monitored repositories</label>
                <p className="text-xs text-muted-alt mb-2">
                    Select which repositories to watch for new issues. Only issues from these repos will create tickets.
                </p>
                <div onFocus={loadGithubRepos}>
                    <RepoCombobox
                        options={repoOptions}
                        value={githubSelectedRepos}
                        onChange={setGithubRepos}
                        placeholder="Select repositories..."
                        disabled={!!adminRestrictionReason || githubReposLoading}
                    />
                </div>
            </div>
        </div>
    )
}

function RepoCombobox({
    options,
    value,
    onChange,
    placeholder,
    disabled,
}: {
    options: { id: string; label: string }[]
    value: string[]
    onChange: (next: string[]) => void
    placeholder: string
    disabled?: boolean
}): JSX.Element {
    const items = options.map((option) => option.id)
    return (
        <Combobox multiple items={items} value={value} onValueChange={onChange}>
            <RepoComboboxBody placeholder={placeholder} disabled={disabled} />
        </Combobox>
    )
}

function RepoComboboxBody({ placeholder, disabled }: { placeholder: string; disabled?: boolean }): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor} className="w-full">
                <ComboboxValue>
                    {(values) => (
                        <>
                            {(values as string[]).map((id) => (
                                <ComboboxChip key={id} title={id}>
                                    {id}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput placeholder={placeholder} disabled={disabled} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matching repositories</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item}>
                            {item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
