import React, { Component } from 'react'
import { NavLink } from 'react-router-dom';

// export default class Sidebar extends Component {
//     render() {
//         return <div className="col-sm-3 col-md-2 sidebar flex-shrink-1 bg-light pt-3" style={{minHeight: '100vh'}}>
//             <ul className="nav flex-sm-column">
//                 <li><NavLink className="nav-link" to="/">Home</NavLink></li>
//                 <li><NavLink className="nav-link" to="/actions">Actions</NavLink></li>
//                 <li><NavLink className="nav-link" to="/events">Events</NavLink></li>
//                 <li><NavLink className="nav-link" to="/people">People</NavLink></li>
//             </ul>
//         </div>
//     }
// }

export default class Sidebar extends Component {
    render() {
        return <div class="left-navigation">
        <div class="row logo-row">
          <img class="logo" src="https://posthog.com/wp-content/uploads/elementor/thumbs/Instagram-Post-1hedgehog-off-black-ok61e8eds76dma39iqao8cwbeihgdc2a9grtrwy6p4.png" />
          <div class="posthog-title">PostHog</div>
        </div>
        <li class="row menu-item">
          <NavLink className="nav-link" to="/actions"><img class="icon-link"src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/click+1.png" />Action Log</NavLink>
            <li class="row menu-item">
              Trends
            </li>
            <li class="row menu-item">
              Configuration
            </li>
        </li>
        <li class="row menu-item">
          <img class="icon-link" src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/users.png" />Users
            <li class="row menu-item">
              Retention
            </li>
            <li class="row menu-item">
              Cohorts
            </li>
        </li>
        <li class="row menu-item">
          <img class="icon-link" src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/cursor+1.png" />Funnels  
        </li>
        <li class="row menu-item">
          <img class="icon-link" src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/target+1.png" />Paths
        </li>
      </div>
    }
}