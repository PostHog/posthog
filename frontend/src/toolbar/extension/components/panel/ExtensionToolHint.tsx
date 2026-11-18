import type { PageToolDefinition } from './extensionPageTools'

export function ExtensionToolHint({ tool }: { tool: PageToolDefinition | null }): JSX.Element {
    return (
        <div className="flex flex-1 flex-col items-center justify-center gap-1 px-4 text-center" aria-live="polite">
            {tool ? (
                <>
                    <span className="text-2xl text-secondary">{tool.icon}</span>
                    <h3 className="m-0 text-sm font-semibold">{tool.label}</h3>
                    <p className="m-0 text-xs text-secondary">{tool.description}</p>
                </>
            ) : (
                <p className="m-0 text-xs text-secondary">Hover a tool to see what it does</p>
            )}
        </div>
    )
}
