import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import './flagPrompt.scss'
import { flagPromptLogic } from './flagPromptLogic'

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
        <div className="FlagPrompt" style={{ display: payload ? 'flex' : 'none', ...openPromptFlag.locationCSS }}>
            <div className="contents">
                {payload.title && <h2 className="title">{payload.title}</h2>}
                {payload.body && <div className="body" dangerouslySetInnerHTML={{ __html: payload.body }} />}
            </div>
            <div className="bottom-section">
                <div
                    className="buttons"
                    style={{
                        justifyContent: payload.primaryButtonText ? 'space-between' : 'center',
                    }}
                >
                    {payload?.secondaryButtonText && (
                        <button
                            className="popup-close-button"
                            onClick={() => closePrompt(openPromptFlag, 'secondary')}
                            // onClick={() => closePopUp(activeFlag, payload, setShowPopup, 'secondary', posthog)}
                        >
                            {payload.secondaryButtonText}
                        </button>
                    )}
                    {payload.primaryButtonText && (
                        <button
                            className="popup-book-button"
                            // onClick={() => closePopUp(activeFlag, payload, setShowPopup, 'primary', posthog)}
                        >
                            {payload.primaryButtonText}
                        </button>
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
