import React, { Component } from 'react'
import { NavLink } from 'react-router-dom';

export default class Sidebar extends Component {
    render() {
        return <div className="col-sm-3 col-md-2 sidebar flex-shrink-1 bg-light pt-3" style={{minHeight: '100vh'}}>
            <ul className="nav flex-sm-column">
                <li><NavLink className="nav-link" to="/">Home</NavLink></li>
                <li><NavLink className="nav-link" to="/events">Events</NavLink></li>
                <li><NavLink className="nav-link" to="/people">People</NavLink></li>
            </ul>
        </div>
    }
}
