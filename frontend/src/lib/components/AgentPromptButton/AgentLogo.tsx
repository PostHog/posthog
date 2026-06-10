import { cn } from 'lib/utils/css-classes'

export { default as claudeLogo } from './logos/claude.svg'
export { default as cursorLogo } from './logos/cursor.svg'
export { default as openaiLogo } from './logos/openai.svg'
export { default as geminiLogo } from './logos/gemini.svg'

export function AgentLogo({
    logo,
    logoClassName,
}: {
    /** Either a brand SVG URL (string from `import foo from './logos/foo.svg'`) or a React node */
    logo: string | React.ReactElement
    /** Extra classes applied to the rendered <img> for brand SVG logos (e.g. `dark:invert` for monochrome marks) */
    logoClassName?: string
}): JSX.Element {
    if (typeof logo !== 'string') {
        return logo
    }
    return <img src={logo} alt="" aria-hidden className={cn('size-4 shrink-0 object-contain', logoClassName)} />
}
