import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { reportsLogic } from './reportsLogic'

export function ReportFolderSetupModal({ folder, teamId }: { folder: string; teamId: number | null }): JSX.Element {
    const logic = reportsLogic({ folder, teamId })
    const {
        folderSetupOpen,
        editingFolder,
        folderForm,
        isFolderFormSubmitting,
        nameSortedDashboards,
        dashboardsLoading,
        loadDashboardsFailed,
    } = useValues(logic)
    const { closeFolderSetup, submitFolderForm, loadDashboards, setFolderFormValue } = useActions(logic)
    return (
        <LemonModal
            isOpen={folderSetupOpen}
            onClose={isFolderFormSubmitting ? undefined : closeFolderSetup}
            title={
                editingFolder ? 'Folder details' : folderForm.teamFolder ? 'Create a team folder' : 'Create a folder'
            }
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeFolderSetup}
                        disabledReason={isFolderFormSubmitting ? 'Saving folder' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitFolderForm}
                        loading={isFolderFormSubmitting}
                        data-attr="reports-save-folder"
                    >
                        {editingFolder ? 'Save changes' : 'Create folder'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={reportsLogic}
                props={{ folder, teamId }}
                formKey="folderForm"
                className="space-y-5"
                enableFormOnSubmit
            >
                <p className="text-secondary m-0">
                    Keep related dashboards, insights, and notes together, with an optional starting dashboard.
                </p>
                <LemonCheckbox
                    checked={folderForm.teamFolder}
                    onChange={(checked) => setFolderFormValue('teamFolder', checked)}
                    label="Identify this as a team folder"
                />
                <LemonField name="name" label={folderForm.teamFolder ? 'Team name' : 'Folder name'}>
                    <LemonInput
                        autoFocus
                        placeholder={
                            folderForm.teamFolder ? 'e.g. Growth or Customer success' : 'e.g. Quarterly reviews'
                        }
                        disabledReason={editingFolder ? 'Rename this folder from Files in the sidebar' : undefined}
                        maxLength={120}
                        data-attr="reports-folder-name"
                    />
                </LemonField>
                <LemonField name="description" label="What is this folder for?" showOptional>
                    <LemonTextArea
                        placeholder="e.g. Acquisition, activation, and our weekly growth review"
                        maxLength={1000}
                        minRows={2}
                        data-attr="reports-folder-description"
                    />
                </LemonField>
                {loadDashboardsFailed && (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Retry', onClick: () => loadDashboards(), loading: dashboardsLoading }}
                    >
                        Could not load dashboards. Try again, or choose a dashboard later.
                    </LemonBanner>
                )}
                <LemonField
                    name="dashboardId"
                    label="Pin a dashboard"
                    showOptional
                    help="Choose a starting point for this folder. You can change it later."
                >
                    <LemonSearchableSelect<number | null>
                        options={[
                            { value: null, label: 'Choose later' },
                            ...nameSortedDashboards.map((dashboard) => ({
                                value: dashboard.id,
                                label: dashboard.name || 'Untitled dashboard',
                            })),
                        ]}
                        searchPlaceholder="Search dashboards"
                        fullWidth
                        disabledReason={dashboardsLoading ? 'Loading dashboards' : undefined}
                        data-attr="reports-folder-dashboard"
                    />
                </LemonField>
                <LemonBanner type="info">
                    This folder uses your project’s existing access rules. Pinning a dashboard does not change who can
                    view it.
                </LemonBanner>
            </Form>
        </LemonModal>
    )
}
