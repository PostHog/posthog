import { LemonButton, LemonDivider, LemonInput, LemonSkeleton, LemonTable, LemonTextArea } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { CodeSnippet } from 'lib/components/CodeSnippet/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ReferralProgram } from '~/types'

import { referralProgramLogic } from './referralProgramLogic'

export const scene: SceneExport = {
    component: ReferralProgramScene,
    logic: referralProgramLogic,
    paramsToProps: ({ params: { id } }): (typeof referralProgramLogic)['props'] => ({
        id: id && id !== 'new' ? id : 'new',
    }),
}

export function ReferralProgramScene({ id }: { id?: string } = {}): JSX.Element {
    const {
        referralProgram,
        referralProgramLoading,
        isReferralProgramSubmitting,
        isEditingProgram,
        referralProgramMissing,
    } = useValues(referralProgramLogic)
    const { submitReferralProgramRequest, loadReferralProgram, editProgram } = useActions(referralProgramLogic)

    const isNewReferralProgram = id === 'new' || id === undefined

    if (referralProgramMissing) {
        return <NotFound object="early access program" />
    }

    if (referralProgramLoading) {
        return <LemonSkeleton active />
    }

    return (
        <>
            <Form id="early-access-program" formKey="referralProgram" logic={referralProgramLogic}>
                <PageHeader
                    buttons={
                        !referralProgramLoading ? (
                            isNewReferralProgram || isEditingProgram ? (
                                <>
                                    <LemonButton
                                        type="secondary"
                                        data-attr="cancel-program"
                                        onClick={() => {
                                            if (isEditingProgram) {
                                                editProgram(false)
                                                loadReferralProgram()
                                            } else {
                                                router.actions.push(urls.referralPrograms())
                                            }
                                        }}
                                        disabledReason={isReferralProgramSubmitting ? 'Saving…' : undefined}
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        htmlType="submit"
                                        data-attr="save-referral-program"
                                        onClick={() => {
                                            submitReferralProgramRequest(referralProgram)
                                        }}
                                        loading={isReferralProgramSubmitting}
                                        form="referral-program"
                                    >
                                        Save
                                    </LemonButton>
                                </>
                            ) : (
                                <>
                                    <LemonButton
                                        data-attr="delete-program"
                                        status="danger"
                                        type="secondary"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Permanently delete program?',
                                                description:
                                                    'You and your users will no longer be able to use this program.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    type: 'primary',
                                                    status: 'danger',
                                                    'data-attr': 'confirm-delete-program',
                                                    onClick: () => {
                                                        // conditional above ensures referralProgram is not NewReferralProgram
                                                        // TODO: Implement deleteReferralProgram
                                                        // deleteReferralProgram(
                                                        //     (referralProgram as ReferralProgramType)?.id
                                                        // )
                                                    },
                                                },
                                                secondaryButton: {
                                                    children: 'Close',
                                                    type: 'secondary',
                                                },
                                            })
                                        }}
                                    >
                                        Delete (but not really, it doesn't work yet)
                                    </LemonButton>
                                    <LemonDivider vertical />
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => editProgram(true)}
                                        loading={false}
                                        data-attr="edit-program"
                                    >
                                        Edit
                                    </LemonButton>
                                </>
                            )
                        ) : undefined
                    }
                    delimited
                />
                <div className={clsx(isEditingProgram || isNewReferralProgram ? 'max-w-160' : null)}>
                    <div className="flex flex-col gap-4 flex-2 min-w-[15rem]">
                        {(isNewReferralProgram || isEditingProgram) && (
                            <LemonField name="title" label="Title">
                                <LemonInput data-attr="program-title" />
                            </LemonField>
                        )}
                        <div className="flex flex-wrap gap-4 items-start">
                            <div className="flex-1 min-w-[20rem]">
                                {isEditingProgram || isNewReferralProgram ? (
                                    <LemonField name="description" label="Description" showOptional>
                                        <LemonTextArea
                                            className="ph-ignore-input"
                                            placeholder="Help your users understand the program"
                                        />
                                    </LemonField>
                                ) : (
                                    <div className="mb-2">
                                        <b>Description</b>
                                        <div>
                                            {referralProgram.description ? (
                                                referralProgram.description
                                            ) : (
                                                <span className="text-muted">No description</span>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-4 items-start">
                            <div className="flex-1 min-w-[20rem]">
                                {isEditingProgram || isNewReferralProgram ? (
                                    <LemonField
                                        name="max_total_redemption_count"
                                        label="Maximum program redemptions"
                                        help="The number of times this program can be redeemed in total. Leave blank for unlimited."
                                        showOptional
                                    >
                                        <LemonInput type="number" />
                                    </LemonField>
                                ) : (
                                    <div className="mb-2">
                                        <b>Redemptions</b>
                                        <p className="mb-0">
                                            <span className="text-lg font-bold">
                                                {referralProgram.redeemers_count || 0}
                                            </span>
                                            {referralProgram.max_total_redemption_count && (
                                                <span className="text-sm text-muted">
                                                    /{referralProgram.max_total_redemption_count}
                                                </span>
                                            )}
                                        </p>
                                        {!referralProgram.max_redemption_count_per_referrer ||
                                            (referralProgram.max_redemption_count_per_referrer > 0 && (
                                                <p className="italic text-muted text-xs">
                                                    Limit {referralProgram.max_redemption_count_per_referrer} redemption
                                                    per referrer.
                                                </p>
                                            ))}
                                    </div>
                                )}
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-4 items-start">
                            <div className="flex-1 min-w-[20rem]">
                                {(isEditingProgram || isNewReferralProgram) && (
                                    <LemonField
                                        name="max_redemption_count_per_referrer"
                                        label="Redemption limit per referrer"
                                        help="The number of times this program can be redeemed for each referrer. Leave blank for unlimited."
                                        showOptional
                                    >
                                        <LemonInput type="number" />
                                    </LemonField>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </Form>
            {!isNewReferralProgram && !isEditingProgram && (
                <ReferralProgramReferrersTable referralProgram={referralProgram} />
            )}
        </>
    )
}

const ReferralProgramReferrersTable = ({ referralProgram }: { referralProgram: ReferralProgram }): JSX.Element => {
    const { programReferrers, programReferrersLoading } = useValues(
        referralProgramLogic({ id: referralProgram.short_id })
    )

    return (
        <div>
            <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Referrers</h2>
                <LemonButton type="primary">Add referrer</LemonButton>
            </div>
            {programReferrersLoading ? (
                <LemonSkeleton active />
            ) : (
                <LemonTable
                    columns={[
                        {
                            key: 'user_id',
                            dataIndex: 'user_id',
                            title: 'Referrer ID',
                        },
                        {
                            key: 'code',
                            dataIndex: 'code',
                            title: 'Code',
                            render: (value) => <CodeSnippet compact>{value}</CodeSnippet>,
                        },
                        {
                            key: 'created_at',
                            dataIndex: 'created_at',
                            title: 'Created at',
                        },
                        {
                            key: 'total_redemptions',
                            dataIndex: 'total_redemptions',
                            title: 'Total redemptions',
                            render: (value) => value || 0,
                        },
                    ]}
                    dataSource={programReferrers}
                    loading={programReferrersLoading}
                    emptyState="No referrers for this program yet. Create one!"
                />
            )}
        </div>
    )
}
