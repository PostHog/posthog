import { SearchResult as SearchResultType } from './types'
import { Link } from '@posthog/lemon-ui'
import { resultTypeToName } from './constants'

type SearchResultProps = {
    result: SearchResultType
}

const SearchResult = ({ result }: SearchResultProps): JSX.Element => (
    <Link className="w-full">
        <div className="w-full pl-3 pr-2 bg-secondary-3000 hover:bg-secondary-3000-hover border-b">
            <div className="px-2 py-3 w-full space-y-0.5 flex flex-col items-start">
                <span className="text-muted-3000 text-xs">{resultTypeToName[result.type]}</span>
                <span className="text-text-3000">{result.name}</span>
                <span className="text-trace-3000 text-xs">
                    app.posthog.com/
                    <span className="text-muted-3000">
                        {result.type}/{result.pk}
                    </span>
                </span>
            </div>
        </div>
    </Link>
)

export default SearchResult
