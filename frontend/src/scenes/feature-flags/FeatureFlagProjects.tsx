import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonButton, LemonModal, LemonModalProps, LemonSelect } from '@posthog/lemon-ui'
import { IconArrowRight } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from './featureFlagLogic'
import { organizationLogic } from '../organizationLogic'

const records: Record<string, string>[] = [{ project: 'project-1-staging', flag_status: 'enabled' }]

export function CopyFeatureFlagModal({
    overlayRef,
    contentRef,
}: Pick<LemonModalProps, 'overlayRef' | 'contentRef'>): JSX.Element {
    const { featureFlag, isProjectsModalOpen } = useValues(featureFlagLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { closeProjectsModal } = useActions(featureFlagLogic)

    return (
        <LemonModal
            overlayRef={overlayRef}
            contentRef={contentRef}
            isOpen={isProjectsModalOpen}
            onClose={closeProjectsModal}
            title="Feature Flag copy"
            description="Copy your flag and its configuration to another project"
            footer={
                <div className="flex-1 flex items-center justify-between">
                    <div className="flex items-center gap-2" />
                    <div className="flex items-center gap-2">
                        <LemonButton form="ff-copy-modal-form" type="secondary" onClick={closeProjectsModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton htmlType="submit" type="primary">
                            Copy
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="max-w-120">
                <Form
                    logic={featureFlagLogic}
                    formKey="ffCopyModal"
                    id="ff-copy-modal-form"
                    enableFormOnSubmit
                    className="space-y-4"
                >
                    <div className="flex gap-2">
                        <div className="flex gap-2 flex-1 flex-col">
                            <div className="font-semibold leading-6 h-6">Feature Flag key</div>
                            <div className="border px-3 rounded h-10 text-center flex items-center justify-center max-w-200">
                                <span className="font-semibold truncate">{featureFlag.key}</span>
                            </div>
                        </div>
                        <div className="flex gap-2 flex-1 flex-col items-center max-w-10">
                            <div className="h-6" />
                            <IconArrowRight className="h-10" fontSize="30" />
                        </div>
                        <Field name="Project" label="Project" className="flex-1">
                            <LemonSelect
                                value={currentOrganization?.teams?.[0].id}
                                options={
                                    currentOrganization?.teams?.map((team) => ({ value: team.id, label: team.name })) || []
                                }
                                className="min-w-40"
                            />
                        </Field>
                    </div>
                </Form>
                <LemonBanner type="warning" className="mt-4">
                    By performing the copy, you may overwrite your existing Feature Flag configuration in
                    project-1-prod.
                </LemonBanner>
            </div>
        </LemonModal>
    )
}

const columns: LemonTableColumns<Record<string, string>> = [
    {
        title: 'Project',
        dataIndex: 'project',
    },
    {
        title: 'Flag status',
        dataIndex: 'flag_status',
    },
]

export default function FeatureFlagProjects(): JSX.Element {
    const { openProjectsModal } = useActions(featureFlagLogic)

    return (
        <div>
            <LemonButton
                type="primary"
                data-attr="copy-feature-flag"
                className="mb-4"
                fullWidth={false}
                onClick={() => openProjectsModal()}
            >
                Copy to another project
            </LemonButton>
            <LemonTable
                dataSource={records}
                columns={columns}
                emptyState="This feature flag is not being used in any other project."
            />
            <CopyFeatureFlagModal />
        </div>
    )
}
