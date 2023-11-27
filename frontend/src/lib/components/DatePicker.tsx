import './DatePicker.scss'

import generatePicker from 'antd/lib/date-picker/generatePicker'
import { dayjs } from 'lib/dayjs'
import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'

export const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)
