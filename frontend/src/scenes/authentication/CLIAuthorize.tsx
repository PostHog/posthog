import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Fragment, useEffect, useState } from 'react'

import { IconCode, IconGear, IconWarning } from '@posthog/icons'
import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { API_SCOPES } from 'lib/scopes'
import { capitalizeFirstLetter } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { cliAuthorizeLogic } from './cliAuthorizeLogic'

export const scene: SceneExport = {
    component: CLIAuthorize,
    logic: cliAuthorizeLogic,
}

function ScopesList({
    scopes,
    formScopeRadioValues,
    displayScopeValues,
    setScopeRadioValue,
    showAll = false,
}: {
    scopes: typeof API_SCOPES
    formScopeRadioValues: Record<string, string>
    displayScopeValues?: Record<string, string>
    setScopeRadioValue: (key: string, action: string) => void
    showAll?: boolean
}): JSX.Element {
    // Use displayScopeValues for filtering if provided, otherwise use formScopeRadioValues
    const filterValues = displayScopeValues ?? formScopeRadioValues
    const visibleScopes = showAll
        ? scopes
        : scopes.filter((scope) => filterValues[scope.key] && filterValues[scope.key] !== 'none')

    if (!showAll && visibleScopes.length === 0) {
        return (
            <div className="text-muted text-sm italic py-2">
                No scopes selected. Click "Manage scopes" to select permissions.
            </div>
        )
    }

    return (
        <div>
            {visibleScopes.map(({ key, disabledActions, warnings, info }) => {
                return (
                    <Fragment key={key}>
                        <div className="flex items-center justify-between gap-2 min-h-8">
                            <div className="flex items-center gap-1">
                                <b>{capitalizeFirstLetter(key.replace(/_/g, ' '))}</b>

                                {info ? (
                                    <Tooltip title={info}>
                                        <IconInfo className="text-secondary text-base" />
                                    </Tooltip>
                                ) : null}
                            </div>
                            <LemonSegmentedButton
                                onChange={(value) => setScopeRadioValue(key, value)}
                                value={formScopeRadioValues[key] ?? 'none'}
                                options={[
                                    { label: 'No access', value: 'none' },
                                    {
                                        label: 'Read',
                                        value: 'read',
                                        disabledReason: disabledActions?.includes('read')
                                            ? 'Does not apply to this resource'
                                            : undefined,
                                    },
                                    {
                                        label: 'Write',
                                        value: 'write',
                                        disabledReason: disabledActions?.includes('write')
                                            ? 'Does not apply to this resource'
                                            : undefined,
                                    },
                                ]}
                                size="xsmall"
                            />
                        </div>
                        {warnings?.[formScopeRadioValues[key]] && (
                            <div className="flex items-start gap-2 text-xs italic pb-2">
                                <IconWarning className="text-base text-secondary mt-0.5" />
                                <span>{warnings[formScopeRadioValues[key]]}</span>
                            </div>
                        )}
                    </Fragment>
                )
            })}
        </div>
    )
}

export function CLIAuthorize(): JSX.Element {
    const {
        authorize,
        isSuccess,
        projects,
        projectsLoading,
        isAuthorizeSubmitting,
        formScopeRadioValues,
        missingSchemaScopes,
        missingErrorTrackingScopes,
    } = useValues(cliAuthorizeLogic)
    const { setAuthorizeValue, setScopeRadioValue } = useActions(cliAuthorizeLogic)
    const [isScopesModalOpen, setIsScopesModalOpen] = useState(false)
    const [displayedScopeValues, setDisplayedScopeValues] = useState<Record<string, string>>({})

    // Initialize displayed values only once when form values are first loaded
    useEffect(() => {
        if (Object.keys(displayedScopeValues).length === 0 && Object.keys(formScopeRadioValues).length > 0) {
            setDisplayedScopeValues(formScopeRadioValues)
        }
    }, [formScopeRadioValues, displayedScopeValues])

    const handleOpenModal = (): void => {
        setIsScopesModalOpen(true)
    }

    const handleCloseModal = (): void => {
        setDisplayedScopeValues(formScopeRadioValues)
        setIsScopesModalOpen(false)
    }

    return (
        <BridgePage
            view="login"
            {...(!isSuccess
                ? {
                      hedgehog: true as const,
                      message: (
                          <>
                              Authorize
                              <br />
                              PostHog CLI
                          </>
                      ),
                  }
                : { hedgehog: false as const })}
        >
            {isSuccess ? (
                <div className="text-center space-y-4">
                    <h2>CLI Authorization Complete</h2>
                    <LemonBanner type="success">
                        <div className="space-y-2">
                            <p className="font-semibold">Your CLI has been authorized successfully!</p>
                            <p>You can now close this window and return to your terminal.</p>
                        </div>
                    </LemonBanner>
                    <div className="text-muted text-sm mt-4">
                        <p>
                            A Personal API Key has been created for your CLI. You can manage your API keys in{' '}
                            <Link to={urls.settings('user-api-keys')} className="font-semibold">
                                Settings → Personal API Keys
                            </Link>
                        </p>
                    </div>
                </div>
            ) : (
                <div className="space-y-4">
                    <h2>Authorize CLI Access</h2>
                    <p className="text-muted text-sm">
                        The PostHog CLI should have displayed a 9-character code (e.g., ABCD-1234). Enter it below to
                        authorize your CLI.
                    </p>
                    <Form logic={cliAuthorizeLogic} formKey="authorize" enableFormOnSubmit className="space-y-4">
                        <LemonField name="userCode" label="Authorization Code">
                            <LemonInput
                                className="ph-ignore-input font-mono text-lg tracking-wider"
                                autoFocus
                                data-attr="cli-auth-code"
                                placeholder="ABCD-1234"
                                maxLength={9}
                                value={authorize.userCode}
                                onChange={(value) => setAuthorizeValue('userCode', value.toUpperCase())}
                                autoComplete="off"
                                autoCorrect="off"
                                autoCapitalize="characters"
                                spellCheck={false}
                            />
                        </LemonField>
                        <LemonField name="projectId" label="Project">
                            <LemonSelect
                                data-attr="cli-project-select"
                                placeholder="Select a project"
                                value={authorize.projectId}
                                onChange={(value) => setAuthorizeValue('projectId', value)}
                                options={projects.map((project: { id: number; name: string }) => ({
                                    label: project.name,
                                    value: project.id,
                                }))}
                                loading={projectsLoading}
                            />
                        </LemonField>

                        <div className="mt-4 mb-2">
                            <div className="flex items-center justify-between mb-2">
                                <h3>Scopes</h3>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconGear />}
                                    onClick={handleOpenModal}
                                >
                                    Manage scopes
                                </LemonButton>
                            </div>
                            <p className="text-muted text-sm mb-2">
                                Selected permissions for the CLI. Only grant the scopes you need.
                            </p>
                        </div>

                        <LemonField name="scopes">
                            {({ error }) => (
                                <>
                                    {error && (
                                        <div className="text-danger flex items-center gap-1 text-sm mb-2">
                                            <IconErrorOutline className="text-xl" /> {error}
                                        </div>
                                    )}

                                    <ScopesList
                                        scopes={API_SCOPES}
                                        formScopeRadioValues={formScopeRadioValues}
                                        displayScopeValues={displayedScopeValues}
                                        setScopeRadioValue={setScopeRadioValue}
                                        showAll={false}
                                    />
                                </>
                            )}
                        </LemonField>

                        <LemonModal
                            title="Manage CLI Scopes"
                            description="Select which permissions to grant to the CLI. Only select the scopes you need."
                            isOpen={isScopesModalOpen}
                            onClose={handleCloseModal}
                            footer={
                                <LemonButton type="primary" onClick={handleCloseModal}>
                                    Done
                                </LemonButton>
                            }
                        >
                            <div className="max-h-96 overflow-y-auto">
                                <ScopesList
                                    scopes={API_SCOPES}
                                    formScopeRadioValues={formScopeRadioValues}
                                    setScopeRadioValue={setScopeRadioValue}
                                    showAll={true}
                                />
                            </div>
                        </LemonModal>

                        {(missingSchemaScopes || missingErrorTrackingScopes) && (
                            <div className="space-y-2 mt-2">
                                {missingSchemaScopes && (
                                    <LemonBanner type="warning">
                                        <b>Schema management unavailable:</b> The CLI needs both{' '}
                                        <code>event_definition</code> and <code>property_definition</code> permissions
                                        (read or write) to manage schemas.
                                    </LemonBanner>
                                )}
                                {missingErrorTrackingScopes && (
                                    <LemonBanner type="warning">
                                        <b>Error tracking unavailable:</b> The CLI needs <code>error_tracking</code>{' '}
                                        permissions (read or write) to manage error tracking.
                                    </LemonBanner>
                                )}
                            </div>
                        )}

                        <LemonButton
                            type="primary"
                            status="alt"
                            htmlType="submit"
                            data-attr="cli-authorize-submit"
                            fullWidth
                            center
                            loading={isAuthorizeSubmitting}
                            size="large"
                            icon={<IconCode />}
                        >
                            Authorize CLI
                        </LemonButton>
                    </Form>
                </div>
            )}
        </BridgePage>
    )
}
