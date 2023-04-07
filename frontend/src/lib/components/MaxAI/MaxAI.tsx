import { LemonButton } from '@posthog/lemon-ui'
import { ChatHog } from '../hedgehogs'
import './maxAI.scss'
import { ChatWindow } from './ChatWindow'
import { useActions, useValues } from 'kea'
import { maxAILogic } from './maxAILogic'

export default function MaxAI(): JSX.Element {
    const { isChatActive } = useValues(maxAILogic)
    const { setIsChatActive } = useActions(maxAILogic)
    const handleClick = (): void => {
        setIsChatActive(true)
    }
    return (
        <>
            <div className="MaxAI fixed bottom-0 right-0 text-left group z-[9999999999]">
                {/* need to make the below take up the full screen on smaller screens */}
                <div className={`MaxAI--window p-4 ${isChatActive ? 'block h-180 w-140' : 'hidden'}`}>
                    {isChatActive ? (
                        <ChatWindow setIsChatActive={setIsChatActive} />
                    ) : (
                        <div className="max-w-80 p-4 bg-white rounded-md shadow-lg">
                            <h3 className="text-lg">Questions about PostHog?</h3>
                            <p className="m-0 text-sm mb-4">Our friendly AI hedgehog Max is here to help!</p>
                            <LemonButton type="primary" onClick={handleClick}>
                                Ask a question
                            </LemonButton>
                        </div>
                    )}
                    <svg
                        style={{ transform: 'translate(70%)', left: '65%' }}
                        className={`absolute ${isChatActive && 'hidden md:block'}`}
                        width="18"
                        height="12"
                        viewBox="0 0 18 12"
                        fill="none"
                        xmlns="http://www.w3.org/2000/svg"
                    >
                        <path d="M18 0H0L18 12V0Z" fill="white" />
                    </svg>
                </div>
                <div className={`md:block mr-2 h-20 flex justify-end`}>
                    <ChatHog className="h-full" />
                </div>
            </div>
        </>
    )
}
