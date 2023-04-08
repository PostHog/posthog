import { ChatHogCircle } from '../hedgehogs'
import './maxAI.scss'
import { ChatWindow } from './ChatWindow'
import { useValues } from 'kea'
import { maxAILogic } from './maxAILogic'

export default function MaxAI(): JSX.Element {
    const { isChatActive } = useValues(maxAILogic)
    return (
        <>
            {isChatActive && (
                <div className="MaxAI fixed bottom-0 right-0 text-left group z-100">
                    {/* need to make the below take up the full screen on smaller screens */}
                    <div className={`MaxAI--window p-4 block h-180 w-140`}>
                        <ChatWindow />
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
                    <div className={`md:block mr-2 h-16 flex justify-end`}>
                        <div className="bg-danger rounded-full h-12 w-12 hover:cursor-pointer">
                            <ChatHogCircle className="h-full w-full" />
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}
