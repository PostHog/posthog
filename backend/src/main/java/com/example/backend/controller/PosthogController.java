package com.example.backend.controller;

import com.example.backend.model.ApiHeatmapGetDTO;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;

import com.example.backend.services.*;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.ArrayList;
import java.util.List;

/**
 * posthogController
 */
@Controller
@RequestMapping("/api/heatmap")
public class PosthogController {

    EventsService eventsService;

    @GetMapping
    public ResponseEntity<List<ApiHeatmapGetDTO>> getAllHeatmap(@RequestParam String query) {
        List<ApiHeatmapGetDTO> results = new ArrayList<>();
        results = eventsService.getAllHeatmap(query);
        return new ResponseEntity<>(results, HttpStatus.OK);
    }
}
