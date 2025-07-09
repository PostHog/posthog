import { useMountedLogic, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

// Inline MOCK_NODE_PROCESS to avoid circular dependency
const MOCK_NODE_PROCESS = { cwd: () => '', env: {} } as unknown as NodeJS.Process
window.process = MOCK_NODE_PROCESS

export function VeryMinimalApp(): JSX.Element {
    const { user } = useValues(userLogic)
    
    return (
        <div style={{padding: '20px', backgroundColor: 'lightblue', fontSize: '24px'}}>
            🎉 Very Minimal App Working!
            <br />
            Time: {new Date().toLocaleTimeString()}
            <br />
            User loaded: {user ? 'Yes' : 'No'}
            <br />
            User email: {user?.email || 'Not available'}
        </div>
    )
} 