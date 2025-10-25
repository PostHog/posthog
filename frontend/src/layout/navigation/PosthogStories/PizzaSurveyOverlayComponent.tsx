import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { CloseOverlayAction } from './storiesMap'

interface PizzaSurveyOverlayComponentProps {
    closeOverlay: (action?: CloseOverlayAction) => void
}

export const PizzaSurveyOverlayComponent = ({ closeOverlay }: PizzaSurveyOverlayComponentProps): JSX.Element => {
    const clickPollButton = (): void => {
        setTimeout(() => {
            const button = document.getElementById('hogtok-pineapple-pizza-poll-button')
            if (button) {
                button.click()
            }
        }, 1000)
    }

    useEffect(() => {
        clickPollButton()

        const handleResize = (): void => {
            clickPollButton()
        }

        window.addEventListener('resize', handleResize)

        return () => {
            window.removeEventListener('resize', handleResize)
        }
    }, [])

    return (
        <div className="flex flex-col h-full bg-primary p-8">
            <div className="flex-1 flex items-start justify-center">
                <LemonButton id="hogtok-pineapple-pizza-poll-button" type="secondary">
                    Take survey
                </LemonButton>
            </div>

            <div className="flex-1 flex items-center justify-center text-3xl">
                <strong>
                    There's only <em>one</em> right answer!
                </strong>
            </div>

            <div className="flex-1 flex items-end justify-center">
                <LemonButton onClick={() => closeOverlay(CloseOverlayAction.Modal)} status="danger">
                    Close
                </LemonButton>
            </div>
        </div>
    )
}
