import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Field,
    FieldLabel,
    Spinner,
    Text,
} from '@posthog/quill'

import { useRepositories } from 'lib/integrations/GitHubIntegrationHelpers'

import { onboardingWizardRunLogic } from 'products/wizard/frontend/views/onboarding/onboardingWizardRunLogic'
import {
    type WizardOnboardingCloudRunProps,
    wizardOnboardingCloudRunLogic,
} from 'products/wizard/frontend/views/onboarding/wizardOnboardingCloudRunLogic'

function RepositoryPicker({
    integrationId,
    value,
    onChange,
}: {
    integrationId: number
    value: string
    onChange: (repository: string) => void
}): JSX.Element {
    const { options, loading } = useRepositories(integrationId, { valueKey: 'full_name' })
    const keys = options.map((option) => String(option.key))

    return (
        <Field>
            <FieldLabel htmlFor="guided-onboarding-cloud-repository">GitHub repository</FieldLabel>
            <Combobox items={keys} value={value || null} onValueChange={(next) => next && onChange(String(next))}>
                <ComboboxInput
                    id="guided-onboarding-cloud-repository"
                    placeholder={loading ? 'Loading repositories' : 'Search repositories'}
                    data-attr="guided-onboarding-cloud-repository"
                />
                <ComboboxContent>
                    <ComboboxEmpty>No repositories found</ComboboxEmpty>
                    <ComboboxList>
                        {(key: string) => (
                            <ComboboxItem key={key} value={key}>
                                {key}
                            </ComboboxItem>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        </Field>
    )
}

/** Quill view over the onboarding cloud run logic: the setup agent runs in the cloud and opens a pull request. */
export function CloudRunPanel(props: WizardOnboardingCloudRunProps): JSX.Element {
    const logic = wizardOnboardingCloudRunLogic(props)
    const {
        cloudRunEnabled,
        runActive,
        repository,
        githubIntegration,
        setupLoading,
        setupError,
        startLabel,
        program,
        createRunRequestLoading,
        createError,
        connectGitHubUrl,
    } = useValues(logic)
    const { setRepository, startCloudRun, retrySetup } = useActions(logic)
    const { run } = useValues(onboardingWizardRunLogic(props))

    if (!cloudRunEnabled) {
        return (
            <Text size="sm" variant="muted">
                Cloud runs aren't available for this project. Pick another option to install PostHog.
            </Text>
        )
    }
    if (runActive) {
        return (
            <div className="flex items-center gap-2" data-attr="guided-onboarding-cloud-run-active">
                <Spinner />
                <Text size="sm">The setup agent is installing PostHog. You can keep going while it runs.</Text>
            </div>
        )
    }
    if (run?.status === 'completed') {
        return (
            <Text size="sm">
                The setup agent opened a pull request in{' '}
                {'repository' in run.workspace ? run.workspace.repository : 'your repository'}. Merge it to start
                sending events.
            </Text>
        )
    }
    if (setupLoading) {
        return <Spinner />
    }
    if (setupError) {
        return (
            <div className="flex flex-col items-start gap-2">
                <Text size="sm" variant="destructive">
                    {setupError}
                </Text>
                <Button variant="outline" onClick={() => retrySetup()}>
                    Retry
                </Button>
            </div>
        )
    }
    if (!program) {
        return (
            <Text size="sm" variant="muted">
                Cloud setup isn't available right now. Pick another option to install PostHog.
            </Text>
        )
    }
    if (!githubIntegration) {
        return (
            <div className="flex flex-col items-start gap-2">
                <Text size="sm" variant="muted">
                    Connect GitHub so the setup agent can open a pull request in your repository.
                </Text>
                <Button
                    variant="outline"
                    render={
                        // eslint-disable-next-line react/forbid-elements
                        <a href={connectGitHubUrl} />
                    }
                    data-attr="guided-onboarding-cloud-connect-github"
                >
                    <IconGithub />
                    Connect GitHub
                </Button>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-start gap-4">
            <RepositoryPicker integrationId={githubIntegration.id} value={repository} onChange={setRepository} />
            {createError && (
                <Text size="sm" variant="destructive">
                    {createError}
                </Text>
            )}
            <Button
                variant="outline"
                onClick={() => startCloudRun()}
                loading={createRunRequestLoading}
                disabledReason={!repository ? 'Select a repository first' : undefined}
                data-attr="guided-onboarding-cloud-run-start"
            >
                {startLabel}
            </Button>
        </div>
    )
}
