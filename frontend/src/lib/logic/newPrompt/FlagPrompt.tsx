import { useActions, useValues } from 'kea'
import './flagPrompt.scss'
import { flagPromptLogic } from './flagPromptLogic'
import clsx from 'clsx'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { PromptButtonType, PromptFlag, PromptPayload } from '~/types'
import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'

function ModalPrompt(
    payload: PromptPayload,
    closePrompt: (promptFlag: PromptFlag, buttonType: PromptButtonType) => void,
    openPromptFlag: PromptFlag
): JSX.Element {
    return (
        <LemonModal
            onClose={() => closePrompt(openPromptFlag, 'secondary')}
            footer={
                (payload.secondaryButtonText || payload.primaryButtonText) && (
                    <div className="flex flex-wrap items-center w-full gap-4 justify-end">
                        {
                            <LemonButton onClick={() => closePrompt(openPromptFlag, 'secondary')} type="secondary">
                                {payload.secondaryButtonText || 'Dismiss'}
                            </LemonButton>
                        }
                        {payload.primaryButtonText && (
                            <LemonButton onClick={() => closePrompt(openPromptFlag, 'primary')} type="primary">
                                {payload.primaryButtonText}
                            </LemonButton>
                        )}
                    </div>
                )
            }
        >
            <div className="w-120">
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

function PopupPrompt(
    payload: PromptPayload,
    openPromptFlag: PromptFlag,
    closePrompt: (promptFlag: PromptFlag, buttonType: PromptButtonType) => void
): JSX.Element {
    return (
        <div className={clsx('PromptPopup max-w-80', payload ? 'flex' : 'none')}>
            <div className="pt-2 pb-4 px-2">
                {payload.title && <h3 className="text-xl">{payload.title}</h3>}
                {payload.body && (
                    <div className="text-sm leading-5" dangerouslySetInnerHTML={{ __html: payload.body }} />
                )}
            </div>
            <div className="bottom-section px-2 py-2">
                <div
                    className={clsx(
                        'flex flex-wrap items-center w-full',
                        payload?.secondaryButtonText && payload.primaryButtonText
                            ? 'gap-4 justify-between'
                            : 'justify-center'
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

export function FlagPrompt(): JSX.Element {
    const { payload, openPromptFlag } = useValues(flagPromptLogic)
    const { closePrompt } = useActions(flagPromptLogic)

    if (!payload || !openPromptFlag) {
        return <></>
    }

    if (payload.type === 'modal') {
        return ModalPrompt(payload, closePrompt, openPromptFlag)
    }

    return PopupPrompt(payload, openPromptFlag, closePrompt)
}
