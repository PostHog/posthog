import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, LemonSelect, Link, lemonToast } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { RAISED_OPTIONS } from './constants'
import { startupProgramLogic } from './startupProgramLogic'

const YC_DEAL_BOOKFACE = 'https://bookface.ycombinator.com/deals/687'

/**
 * The application form of step 2.
 *
 * Built from Lemon fields rather than quill ones, because they carry this form's kea-forms
 * wiring, its file upload and its calendar. `data-not-quill` hands them back their own colour
 * tokens inside the page's quill subtree - see styles/quill-bridge.scss.
 */
export function StartupProgramForm(): JSX.Element {
    const { startupProgram, isYC, ycBatchOptions } = useValues(startupProgramLogic)
    const { setStartupProgramValue } = useActions(startupProgramLogic)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url) => {
            setStartupProgramValue('yc_proof_screenshot_url', url)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading screenshot: ${detail}`)
            setStartupProgramValue('yc_proof_screenshot_url', undefined)
        },
    })

    return (
        <div data-not-quill>
            <Form logic={startupProgramLogic} formKey="startupProgram" enableFormOnSubmit className="space-y-3">
                <div className="hidden">
                    <div className="grid md:grid-cols-2 gap-3">
                        <LemonField name="first_name" label="First name">
                            <LemonInput placeholder="Jane" />
                        </LemonField>

                        <LemonField name="last_name" label="Last name">
                            <LemonInput placeholder="Doe" />
                        </LemonField>
                    </div>

                    <LemonField name="email" label="Email">
                        <LemonInput placeholder="you@example.com" />
                    </LemonField>

                    <LemonField name="startup_domain" label="Company domain">
                        <LemonInput placeholder="example.com" />
                    </LemonField>
                </div>

                <LemonField
                    name="organization_name"
                    label="PostHog organization"
                    info="To apply for a different organization, switch to that organization first"
                >
                    <LemonInput placeholder="Your PostHog organization" disabled />
                </LemonField>

                <LemonField name="organization_id" className="hidden">
                    <LemonInput />
                </LemonField>

                {!isYC && (
                    <>
                        <LemonField name="raised" label="How much in total funding have you raised (USD)">
                            <LemonSelect options={RAISED_OPTIONS} className="bg-bg-light" />
                        </LemonField>

                        <LemonField name="incorporation_date" label="The date that your company was incorporated">
                            <LemonCalendarSelectInput
                                clearable={false}
                                format="YYYY-MM-DD"
                                buttonProps={{ className: 'bg-bg-light' }}
                                placeholder=" "
                                selectionPeriod="past"
                            />
                        </LemonField>
                    </>
                )}

                {isYC && (
                    <>
                        <LemonField
                            name="yc_verification_url"
                            label="Your YC verification link"
                            info={
                                <span>
                                    See{' '}
                                    <Link target="_blank" to="https://www.ycombinator.com/verify">
                                        YC's verification docs
                                    </Link>{' '}
                                    for how verification links work. We check your link when you submit the application.
                                </span>
                            }
                            help={
                                <span>
                                    Create a verification link at{' '}
                                    <Link target="_blank" to="https://www.ycombinator.com/verify/manage">
                                        ycombinator.com/verify/manage
                                    </Link>{' '}
                                    with your company details and batch visible, so we can verify you automatically.
                                    Phone number, personal email, and social profiles can be left off.
                                </span>
                            }
                        >
                            <LemonInput
                                placeholder="https://www.ycombinator.com/verify/your-unique-code"
                                className="bg-bg-light"
                            />
                        </LemonField>

                        <LemonField name="yc_batch" label="Which YC batch are you?">
                            <LemonSelect options={ycBatchOptions} className="bg-bg-light" />
                        </LemonField>

                        <LemonField
                            name="yc_proof_screenshot_url"
                            label={
                                <span>
                                    Screenshot showing you're using{' '}
                                    <Link target="_blank" to={YC_DEAL_BOOKFACE}>
                                        PostHog deal
                                    </Link>{' '}
                                    on Bookface
                                </span>
                            }
                            info="Open PostHog deal on Bookface, click 'Mark Using', take a screenshot and attach it below"
                        >
                            <LemonFileInput
                                accept="image/*"
                                multiple={false}
                                value={filesToUpload}
                                showUploadedFiles={false}
                                onChange={setFilesToUpload}
                                loading={uploading}
                                callToAction={
                                    <div className="border border-dashed rounded p-2 w-full">
                                        {startupProgram.yc_proof_screenshot_url ? (
                                            <div className="flex items-center justify-center gap-4 w-full">
                                                <span className="font-semibold">YC deal screenshot</span>
                                                <div className="relative">
                                                    <img
                                                        src={startupProgram.yc_proof_screenshot_url}
                                                        alt="YC Profile"
                                                        className="h-10 w-10 rounded object-cover"
                                                    />
                                                    <LemonButton
                                                        type="tertiary"
                                                        status="danger"
                                                        size="xsmall"
                                                        icon={<IconX className="text-sm" />}
                                                        onClick={(e) => {
                                                            e.preventDefault()
                                                            setStartupProgramValue('yc_proof_screenshot_url', undefined)
                                                        }}
                                                        tooltip="Remove screenshot"
                                                        className="absolute -top-1 -right-1 p-0.5 !bg-bg-light rounded-full"
                                                        noPadding
                                                    />
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="flex items-center justify-center gap-2">
                                                <IconUpload className="text-2xl" />
                                                <span>Upload Screenshot</span>
                                            </div>
                                        )}
                                    </div>
                                }
                            />
                        </LemonField>

                        <LemonField
                            name="yc_merch_count"
                            label="How many merch packs do you need for you and your co-founder(s)?"
                        >
                            <LemonInput type="number" min={1} max={5} />
                        </LemonField>
                    </>
                )}

                <LemonButton type="primary" htmlType="submit" className="mt-4" data-attr="startup-program-submit">
                    Submit Application
                </LemonButton>

                {/* This will display a form error if user is not on a paid plan. Kea forms requires a child element */}
                <LemonField name="_form">
                    <span />
                </LemonField>
            </Form>
        </div>
    )
}
