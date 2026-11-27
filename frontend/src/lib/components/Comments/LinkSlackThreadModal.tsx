import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { CommentsLogicProps } from './commentsLogic'
import { linkSlackThreadLogic } from './linkSlackThreadLogic'
import { SlackDestinationPicker } from './SlackDestinationPicker'

export function LinkSlackThreadModal(props: CommentsLogicProps): JSX.Element {
    const { isOpen, integrationId, url, error, isSubmitting } = useValues(linkSlackThreadLogic(props))
    const { closeModal, setIntegrationId, setUrl, submit } = useActions(linkSlackThreadLogic(props))

    const disabledReason = !integrationId
        ? 'Select a Slack workspace'
        : !url.trim()
          ? 'Paste a Slack message link'
          : null

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Link a Slack thread"
            description="Already discussing this in Slack? Paste a link to any message in the thread. It becomes a discussion here, its earlier replies follow, and from then on replies sync both ways."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        loading={isSubmitting}
                        disabledReason={disabledReason}
                        data-attr="discussions-link-slack-thread-submit"
                    >
                        Link thread
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                {/* No channel to pick: the link says which one the thread is in. */}
                <SlackDestinationPicker integrationId={integrationId} onIntegrationChange={setIntegrationId} />
                <LemonField.Pure label="Slack message link" error={error}>
                    <LemonInput
                        type="url"
                        autoFocus
                        value={url}
                        onChange={setUrl}
                        onPressEnter={disabledReason || isSubmitting ? undefined : submit}
                        placeholder="https://yourcompany.slack.com/archives/…"
                        fullWidth
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}

/** The composer's way in: the button and the modal it opens, both for this one discussion. */
export function LinkSlackThreadButton({ size, ...props }: CommentsLogicProps & { size?: 'small' }): JSX.Element {
    const { openModal } = useActions(linkSlackThreadLogic(props))

    return (
        <>
            <LemonButton
                size={size}
                type="tertiary"
                icon={<IconSlack />}
                onClick={openModal}
                tooltip="Bring a discussion that started in Slack here"
                data-attr="discussions-link-slack-thread"
            >
                Link Slack thread
            </LemonButton>
            <LinkSlackThreadModal {...props} />
        </>
    )
}
