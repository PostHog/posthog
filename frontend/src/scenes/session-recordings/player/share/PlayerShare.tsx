import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { SharingModalContent } from 'lib/components/Sharing/SharingModal'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PlayerShareLogicProps, playerShareLogic } from './playerShareLogic'

function TimestampForm(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { privateLinkForm } = useValues(logic)
    const { setPrivateLinkFormValue } = useActions(logic)

    return (
        <Form logic={playerShareLogic} props={props} formKey="privateLinkForm">
            <div className="flex gap-2 items-center">
                <LemonField name="includeTime">
                    <LemonCheckbox label="Start at" checked={privateLinkForm.includeTime} />
                </LemonField>
                <LemonField name="time" inline>
                    <LemonInput
                        className={clsx('w-20', { 'opacity-50': !privateLinkForm.includeTime })}
                        placeholder="00:00"
                        onFocus={() => setPrivateLinkFormValue('includeTime', true)}
                        fullWidth={false}
                        size="small"
                    />
                </LemonField>
            </div>
        </Form>
    )
}

function PublicLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { privateLinkUrlQueryParams } = useValues(logic)

    return (
        <>
            <p>
                You can share or embed the recording outside of PostHog. Be aware that all the content of the recording
                will be accessible to anyone with the link.
            </p>

            <SharingModalContent
                recordingId={props.id}
                previewIframe
                additionalParams={privateLinkUrlQueryParams}
                recordingLinkTimeForm={<TimestampForm {...props} />}
            />
        </>
    )
}

function PrivateLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { privateLinkUrl, privateLinkFormHasErrors } = useValues(logic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <div>
                    <b>Click the button below</b> to copy a direct link to this recording.
                </div>
                <div>Make sure the person you share it with has access to this PostHog project.</div>
            </div>
            <LemonButton
                type="secondary"
                fullWidth
                center
                sideIcon={<IconCopy />}
                onClick={() =>
                    void copyToClipboard(privateLinkUrl, privateLinkUrl).catch((e) => posthog.captureException(e))
                }
                title={privateLinkUrl}
                disabledReason={privateLinkFormHasErrors ? 'Fix all errors before continuing' : undefined}
            >
                <span className="break-all">{privateLinkUrl}</span>
            </LemonButton>
            <TimestampForm {...props} />
        </div>
    )
}

function LinearLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { linearLinkForm, linearUrl, linearLinkFormHasErrors } = useValues(logic)
    const { setLinearLinkFormValue } = useActions(logic)

    return (
        <>
            <p>Add an issue to your Linear workspace with a link to this recording.</p>

            <Form logic={playerShareLogic} props={props} formKey="linearLinkForm" className="flex flex-col gap-2">
                <LemonField className="gap-1" name="issueTitle" label="Issue title">
                    <LemonInput fullWidth />
                </LemonField>
                <LemonField
                    className="gap-1"
                    name="issueDescription"
                    label="Issue description"
                    help={<span>We'll include a link to the recording in the description.</span>}
                >
                    <LemonTextArea />
                </LemonField>
                <div className="flex gap-1 items-center">
                    <LemonField name="includeTime">
                        <LemonCheckbox label="Start at" checked={linearLinkForm.includeTime} />
                    </LemonField>
                    <LemonField name="time" inline>
                        <LemonInput
                            className={clsx('w-20', { 'opacity-50': !linearLinkForm.includeTime })}
                            onFocus={() => setLinearLinkFormValue('includeTime', true)}
                            placeholder="00:00"
                            fullWidth={false}
                            size="small"
                        />
                    </LemonField>
                </div>
                <LemonCollapse
                    panels={[
                        {
                            key: 'more-options',
                            header: 'More options',
                            content: (
                                <div className="flex flex-col gap-2">
                                    <LemonField
                                        className="gap-1"
                                        name="assignee"
                                        label="Assignee"
                                        help={<span>Linear username or 'me' to assign to yourself</span>}
                                    >
                                        <LemonInput
                                            fullWidth
                                            placeholder="username or me"
                                            data-attr="linear-share-assignee"
                                        />
                                    </LemonField>
                                    <LemonField className="gap-1" name="labels" label="Label">
                                        <LemonInput
                                            fullWidth
                                            placeholder="bug or feature"
                                            data-attr="linear-share-labels"
                                        />
                                    </LemonField>
                                </div>
                            ),
                        },
                    ]}
                    defaultActiveKey={props.expandMoreOptions ? 'more-options' : undefined}
                />
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        to={linearUrl}
                        targetBlank={true}
                        disabledReason={linearLinkFormHasErrors ? 'Fix all errors before continuing' : undefined}
                    >
                        Create issue
                    </LemonButton>
                </div>
            </Form>
        </>
    )
}

function GithubIssueLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { githubLinkForm, githubUrl, githubLinkFormHasErrors } = useValues(logic)
    const { setGithubLinkFormValue } = useActions(logic)

    return (
        <>
            <p>Add an issue to your Github repository with a link to this recording.</p>

            <Form logic={playerShareLogic} props={props} formKey="githubLinkForm" className="flex flex-col gap-2">
                <LemonField className="gap-1" name="githubUsername" label="Username or Organization Name">
                    <LemonInput fullWidth data-attr="github-share-username" />
                </LemonField>
                <LemonField className="gap-1" name="githubRepoName" label="Repository Name">
                    <LemonInput fullWidth data-attr="github-share-repo-name" />
                </LemonField>
                <LemonField className="gap-1" name="githubIssueTitle" label="Issue Title">
                    <LemonInput fullWidth data-attr="github-share-issue-title" />
                </LemonField>
                <LemonField
                    className="gap-1"
                    name="githubIssueDescription"
                    label="Issue description"
                    help={<span>We'll include a link to the recording in the description.</span>}
                >
                    <LemonTextArea />
                </LemonField>
                <div className="flex gap-1 items-center">
                    <LemonField name="includeTime">
                        <LemonCheckbox label="Start at" checked={githubLinkForm.includeTime} />
                    </LemonField>
                    <LemonField name="time" inline>
                        <LemonInput
                            className={clsx('w-20', { 'opacity-50': !githubLinkForm.includeTime })}
                            onFocus={() => setGithubLinkFormValue('includeTime', true)}
                            placeholder="00:00"
                            fullWidth={false}
                            size="small"
                        />
                    </LemonField>
                </div>
                <LemonCollapse
                    panels={[
                        {
                            key: 'more-options',
                            header: 'More options',
                            content: (
                                <div className="flex flex-col gap-2">
                                    <LemonField
                                        className="gap-1"
                                        name="githubAssignees"
                                        label="Assignees"
                                        help={<span>Comma-separated GitHub usernames to assign</span>}
                                    >
                                        <LemonInput
                                            fullWidth
                                            placeholder="user1, user2"
                                            data-attr="github-share-assignees"
                                        />
                                    </LemonField>
                                    <LemonField
                                        className="gap-1"
                                        name="githubLabels"
                                        label="Labels"
                                        help={<span>Comma-separated labels to add to the issue</span>}
                                    >
                                        <LemonInput
                                            fullWidth
                                            placeholder="bug, enhancement"
                                            data-attr="github-share-labels"
                                        />
                                    </LemonField>
                                </div>
                            ),
                        },
                    ]}
                />
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        to={githubUrl}
                        targetBlank={true}
                        disabledReason={
                            !githubUrl
                                ? 'Please fill in Username or Organization Name and Repository Name'
                                : githubLinkFormHasErrors
                                  ? 'Fix all errors before continuing'
                                  : undefined
                        }
                    >
                        Create issue
                    </LemonButton>
                </div>
            </Form>
        </>
    )
}

export function PlayerShareRecording(props: PlayerShareLogicProps): JSX.Element {
    return (
        <div className="gap-y-2">
            {props.shareType === 'private' && <PrivateLink {...props} />}

            {props.shareType === 'public' && <PublicLink {...props} />}

            {props.shareType === 'linear' && <LinearLink {...props} />}

            {props.shareType === 'github' && <GithubIssueLink {...props} />}
        </div>
    )
}

const shareTitleMapping = {
    private: 'Share private link',
    public: 'Share public link',
    linear: 'Share to Linear',
    github: 'Share to Github Issues',
}

export function openPlayerShareDialog(props: PlayerShareLogicProps): void {
    LemonDialog.open({
        title: props.shareType ? shareTitleMapping[props.shareType] : '',
        content: <PlayerShareRecording {...props} />,
        maxWidth: '85vw',
        zIndex: '1162',
        primaryButton: null,
    })
}
