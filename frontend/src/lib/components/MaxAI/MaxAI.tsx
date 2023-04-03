import { LemonButton } from '@posthog/lemon-ui'
import { useState } from 'react'
import { ChatHog } from '../hedgehogs'

export default function MaxAI(): JSX.Element {
    const [isChatActive, setIsChatActive] = useState<boolean>(false)
    const handleClick = (): void => {
        if (typeof window !== 'undefined') {
            setIsChatActive(true)
        }
    }
    return (
        <>
            <div className="fixed bottom-0 right-0 text-left group z-[9999999999]">
                <div
                    className={`p-4 group-hover:block ${
                        isChatActive ? 'block h-screen w-screen md:h-[620px] md:w-[420px]' : 'hidden'
                    }`}
                >
                    {isChatActive ? (
                        // <ChatWindow setIsChatActive={setIsChatActive} />
                        <p>chat window</p>
                    ) : (
                        <div className="max-w-[250px] p-4 bg-white rounded-md shadow-lg">
                            <h3 className="m-0 text-lg">Questions about PostHog?</h3>
                            <p className="m-0 text-sm mb-2">Our friendly AI hedgehog Max is here to help!</p>
                            <LemonButton onClick={handleClick}>Ask a question</LemonButton>
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
                <div className={`text-right md:block mr-2 h-20`}>
                    <ChatHog className="h-full w-full" />
                </div>
            </div>
        </>
    )
}
