import fs from 'fs'
import path from 'path'

import { ALL_TEMPLATES } from '../cdp/templates'

const destination = path.join(__dirname, '..', '..', 'cdp-templates.json')

fs.writeFileSync(destination, JSON.stringify(ALL_TEMPLATES, null, 2))
