import React, { Component } from 'react'
import { NavLink } from 'react-router-dom';
import { withRouter } from 'react-router-dom';

class Sidebar extends Component {
    render() {
        return <div className="sidebar col-sm-3 col-md-2 sidebar flex-shrink-1 bg-light pt-3" style={{minHeight: '100vh'}}>
            <div class="row logo-row">
              <img class="logo" src="https://posthog.com/wp-content/uploads/elementor/thumbs/Instagram-Post-1hedgehog-off-black-ok61e8eds76dma39iqao8cwbeihgdc2a9grtrwy6p4.png" />
              <div class="posthog-title">PostHog</div>
            </div>
            <ul className="nav flex-sm-column">
                <li><NavLink className="nav-link" exact to="/actions"><i className='fi flaticon-click' /> Actions</NavLink></li>
                {this.props.history.location.pathname.indexOf('/action') > -1 && [
                    <li className='nav-indent'><NavLink className='nav-link' to="/actions/live"><i className='fi flaticon-refresh' /> Live actions</NavLink></li>
                ]}
                <li><NavLink className="nav-link" to="/people"><i className='fi flaticon-speech-bubble' /> Users</NavLink></li>
                <li><NavLink className="nav-link" to="/funnels"><i className='fi flaticon-cursor-1' /> Funnels</NavLink></li>
                <li><NavLink className="nav-link" to="/events"><i className='fi flaticon-zoom-in' /> Events</NavLink></li>
            </ul>
        </div>
    }
}
export default withRouter(Sidebar);