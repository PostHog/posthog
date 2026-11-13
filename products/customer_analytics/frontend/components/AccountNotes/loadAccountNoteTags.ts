import { LoadTags } from 'lib/components/tagSelectLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { accountNotesTagsList } from '../../generated/api'

const TAGS_PER_PAGE = 100

/** Suggests only the tags already on account notes, not every tag in the project. */
export const loadAccountNoteTags: LoadTags = async (search, offset) => {
    const page = await accountNotesTagsList(String(getCurrentTeamId()), { search, limit: TAGS_PER_PAGE, offset })
    return {
        results: page.results.map(({ name }) => ({ tag: name })),
        hasMore: page.next != null,
        nextOffset: offset + page.results.length,
    }
}
