/**
 * `/agents/[slug]/configuration` — spec + bundle + revisions browser.
 *
 * Segment-local URL state:
 *   `?revision=<id>`  — selected revision in the master-detail
 *   `?section=<spec>` — highlighted spec section (anchor target)
 *   `?file=<path>`    — selected bundle file
 */

import { ConfigurationSegment } from './configuration-client'

export default function ConfigurationPage(): React.ReactElement {
    return <ConfigurationSegment />
}
