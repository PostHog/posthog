import twigLogo from 'public/twig-logo.svg'

export function TwigAuthLeftPanel(): JSX.Element {
    return (
        <div className="max-w-sm">
            <img src={twigLogo} alt="Twig" className="h-10 mb-6" />
            <h2 className="text-2xl font-semibold leading-tight">the dawn of a new agentic era</h2>
        </div>
    )
}
