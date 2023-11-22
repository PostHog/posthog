import './prompt.scss'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'

import { PromptButtonType, PromptFlag, PromptPayload } from '~/types'

import { promptLogic } from './promptLogic'

export function ModalPrompt({
    payload,
    closePrompt,
    openPromptFlag,
    inline = false,
}: {
    payload: PromptPayload
    closePrompt: (promptFlag: PromptFlag, buttonType: PromptButtonType) => void
    openPromptFlag: PromptFlag
    inline?: boolean
}): JSX.Element {
    return (
        <LemonModal
            onClose={() => closePrompt(openPromptFlag, 'secondary')}
            footer={
                (payload.secondaryButtonText || payload.primaryButtonText) && (
                    <div className="flex flex-wrap items-center w-full gap-4 justify-end">
                        <LemonButton onClick={() => closePrompt(openPromptFlag, 'secondary')} type="secondary">
                            {payload.secondaryButtonText || 'Dismiss'}
                        </LemonButton>
                        {payload.primaryButtonText && (
                            <LemonButton onClick={() => closePrompt(openPromptFlag, 'primary')} type="primary">
                                {payload.primaryButtonText}
                            </LemonButton>
                        )}
                    </div>
                )
            }
            inline={inline}
        >
            <div className="max-w-120">
                <div className="w-full flex items-center justify-center my-8">
                    <div className="w-100 max-h-180">
                        <FallbackCoverImage src={payload.image} index={0} alt={`Prompt image for ${payload.title}`} />
                    </div>
                </div>
                {payload.title && <h3 className="text-3xl">{payload.title}</h3>}

                {payload.body && (
                    <div className="text-sm leading-5 mb-4" dangerouslySetInnerHTML={{ __html: payload.body }} />
                )}
            </div>
        </LemonModal>
    )
}

export function PopupPrompt({
    payload,
    openPromptFlag,
    closePrompt,
    inline = false,
}: {
    payload: PromptPayload
    openPromptFlag: PromptFlag
    closePrompt: (promptFlag: PromptFlag, buttonType: PromptButtonType) => void
    inline?: boolean
}): JSX.Element {
    return (
        <div
            className={clsx('PromptPopup max-w-80', payload ? 'flex' : 'none')}
            // Used for the storybook
            // eslint-disable-next-line react/forbid-dom-props
            style={inline ? { position: 'relative' } : {}}
        >
            {payload.image && (
                <FallbackCoverImage src={payload.image} index={0} alt={`Prompt image for ${payload.title}`} />
            )}
            <div className="pt-2 pb-4 px-2">
                {payload.title && <h3 className="text-xl">{payload.title}</h3>}
                {payload.body && (
                    <div className="text-sm leading-5" dangerouslySetInnerHTML={{ __html: payload.body }} />
                )}
            </div>
            <div className="px-2 py-2">
                <div
                    className={clsx(
                        'flex flex-wrap items-center w-full',
                        payload?.secondaryButtonText && payload.primaryButtonText
                            ? 'gap-4 justify-between'
                            : 'justify-end'
                    )}
                >
                    {payload?.secondaryButtonText && (
                        <LemonButton onClick={() => closePrompt(openPromptFlag, 'secondary')} type="secondary">
                            {payload.secondaryButtonText}
                        </LemonButton>
                    )}
                    {payload.primaryButtonText && (
                        <LemonButton onClick={() => closePrompt(openPromptFlag, 'primary')} type="primary">
                            {payload.primaryButtonText}
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}

export function Prompt(): JSX.Element {
    const { payload, openPromptFlag } = useValues(promptLogic)
    const { closePrompt } = useActions(promptLogic)

    if (!payload || !openPromptFlag) {
        return <></>
    }

    if (payload.type === 'modal') {
        return <ModalPrompt payload={payload} openPromptFlag={openPromptFlag} closePrompt={closePrompt} />
    }

    return <PopupPrompt payload={payload} openPromptFlag={openPromptFlag} closePrompt={closePrompt} />
}
