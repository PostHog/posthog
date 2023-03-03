import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import './flagPrompt.scss'
import { flagPromptLogic } from './flagPromptLogic'
import clsx from 'clsx'
import { LemonButton } from '@posthog/lemon-ui'

export function FlagPrompt(): JSX.Element {
    const { payload, openPromptFlag } = useValues(flagPromptLogic)
    const { closePrompt } = useActions(flagPromptLogic)

    useEffect(() => {
        console.log(payload)
    }, [payload])

    if (!payload) {
        return <></>
    }

    return (
        // dynamic location
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className={clsx('FlagPrompt max-w-80', payload ? 'flex' : 'none')}
            style={{ ...openPromptFlag.locationCSS }}
        >
            <div className="pt-2 pb-4 px-2">
                {payload.title && <h3 className="text-lg">{payload.title}</h3>}
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
            {payload.location && (
                <div
                    style={
                        {
                            // ...generateTooltipPointerStyle(payload.location),
                        }
                    }
                />
            )}
        </div>
    )
}
