// import './style.scss'
import React from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext } from 'kea'

import { initKea } from '~/initKea'

initKea()

ReactDOM.render(<Provider store={getContext().store}>Fun stuff</Provider>, document.getElementById('root'))
