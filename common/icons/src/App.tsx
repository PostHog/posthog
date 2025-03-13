import * as icons from './Icons'

function App() {
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', fontFamily: 'sans-serif' }}>
            {Object.keys(icons).map((key) => {
                const Icon = (icons as Record<string, React.FC<{ title?: string }>>)[key]
                return (
                    <div style={{ width: 80, height: 80, margin: '2rem', textAlign: 'center' }}>
                        <Icon title={key} />
                        <span>{key}</span>
                    </div>
                )
            })}
        </div>
    )
}

export default App
