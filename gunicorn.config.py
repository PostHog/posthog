#!/usr/bin/env python3
# -*- coding: utf-8 -*-


loglevel = "error"

def on_starting(server):
    print("""
\x1b[1;34m
 _____          _   _    _             
|  __ \        | | | |  | |            
| |__) |__  ___| |_| |__| | ___   __ _ 
|  ___/ _ \/ __| __|  __  |/ _ \ / _` |
| |  | (_) \__ \ |_| |  | | (_) | (_| |
|_|   \___/|___/\__|_|  |_|\___/ \__, |
                                  __/ |
                                 |___/ 
\x1b[0m
""")
    print("Server running on \x1b[4mhttp://127.0.0.1:8000\x1b[0m")
    print("Questions? Please shoot us an email at \x1b[4mhey@posthog.com\x1b[0m")
    print("\nTo stop, press CTRL + C")